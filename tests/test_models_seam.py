"""The seam: the shared types both developers build against.

#23 puts this module before everything else, and CONTRIBUTING.md makes it the one
file that needs both developers to agree before a pull request opens. These tests are
what "agreed" is written down as - they are the only tests in this project that touch
a module directly rather than going through a seam above it, and they exist because
24a ships no endpoint to observe the types through yet. Once #24b lands, every further
assertion about behaviour belongs at the HTTP boundary.

There is no maths here and no I/O. What is asserted is the vocabulary: what a Leg is,
what it deliberately does not know, and what a client is not allowed to send.
"""

import pytest
from pydantic import ValidationError

from payoff import models
from payoff.models import (
    AnalysisRequest,
    AnalysisResponse,
    Curve,
    Leg,
    LegGreeks,
    LegRequest,
    Metrics,
)


def test_a_leg_carries_its_own_terms_and_never_its_lot_size():
    """CONTEXT.md: 'A Leg does not know its Lot Size.'

    Lot Size is a presentation multiplier the exchange revises - 65 for NIFTY today.
    Storing it on a Leg would make every stored Leg silently wrong the day it changes,
    so it is applied where results are presented and is absent from the type itself.
    """
    leg = Leg(
        strike=25200.0,
        option_type="CE",
        direction=1,
        quantity=1,
        entry_premium=344.05,
        iv=0.1861,
    )

    assert leg.strike == 25200.0
    assert leg.option_type == "CE"
    assert leg.direction == 1
    assert leg.quantity == 1
    assert leg.entry_premium == 344.05
    assert leg.iv == 0.1861

    assert "lot_size" not in Leg.model_fields


def test_direction_is_separate_from_quantity_and_a_leg_is_never_negative():
    """CONTEXT.md: 'Direction is separate from Quantity - a Leg is never held as a
    negative quantity.'

    Sold two lots is direction -1 and quantity 2, never quantity -2. The two encodings
    would produce the same curve today and disagree the first time anything sums or
    displays Quantity, so only one of them is representable.
    """
    sold = Leg(
        strike=25200.0,
        option_type="PE",
        direction=-1,
        quantity=2,
        entry_premium=326.70,
        iv=0.1861,
    )
    assert sold.direction == -1
    assert sold.quantity == 2

    for invalid in ({"quantity": -2}, {"quantity": 0}, {"direction": 0}, {"option_type": "CALL"}):
        with pytest.raises(ValidationError):
            Leg(
                **{
                    "strike": 25200.0,
                    "option_type": "PE",
                    "direction": -1,
                    "quantity": 2,
                    "entry_premium": 326.70,
                    "iv": 0.1861,
                    **invalid,
                }
            )


def test_a_client_cannot_supply_implied_volatility():
    """#23: 'the client never supplies implied volatility - the server looks it up.'

    A wrong volatility does not fail loudly; it produces a plausible chart that nothing
    downstream would catch. So the request type has no field for it, and unknown fields
    are rejected rather than ignored - silently dropping `iv` would leave a caller
    believing it was honoured.

    Entry Premium is the one price a trader may legitimately supply (story 18, 'what if
    I had entered at X'). It is optional: absent means the Chain's last traded price.
    """
    request = LegRequest(strike=25200.0, option_type="CE", direction=1)
    assert request.quantity == 1, "one contract is the sensible default"
    assert request.entry_premium is None, "absent means take the Chain's last traded price"

    assert "iv" not in LegRequest.model_fields

    for smuggled in ({"iv": 0.01}, {"implied_volatility": 0.01}, {"lot_size": 65}):
        with pytest.raises(ValidationError):
            LegRequest(strike=25200.0, option_type="CE", direction=1, **smuggled)


def test_a_strategy_is_an_ordered_list_of_legs_and_not_a_type():
    """CONTEXT.md: 'A Strategy is an ordered list of Legs. Nothing more.'

    "Iron condor" is a shape four Legs happen to have, not a kind of Strategy. If a
    Strategy type existed, something would eventually branch on it, and #23's rule that
    no metric branches on leg count or shape name would be one refactor from broken.
    A Preset (#30) therefore adds no type here, and no engine code either.
    """
    assert not hasattr(models, "Strategy"), "a Strategy is a list, not a type"

    condor = [
        {"strike": 24800.0, "option_type": "PE", "direction": 1},
        {"strike": 25000.0, "option_type": "PE", "direction": -1},
        {"strike": 25400.0, "option_type": "CE", "direction": -1},
        {"strike": 25600.0, "option_type": "CE", "direction": 1},
    ]
    request = AnalysisRequest(moment="2026-01-27T06:30:00", legs=condor)

    assert [leg.strike for leg in request.legs] == [24800.0, 25000.0, 25400.0, 25600.0]
    assert all(isinstance(leg, LegRequest) for leg in request.legs)


def test_unbounded_is_json_null_and_a_not_a_number_cannot_be_built_at_all():
    """#24: Unbounded serialises as JSON `null`, 'never an infinity token or a string'.

    CONTEXT.md keeps the two apart: Unbounded is a real state a maximum can be in, and
    a trader reads it as "Unlimited". A NaN is not a state - it is a mistake. ADR-0001
    bans it in the core and the API contract bans it on the wire, because it renders as
    a silent gap in a chart and survives review.

    So the ban is enforced by the type: a NaN or an infinity cannot be put into Metrics
    in the first place, which means it cannot reach the wire however the layer above is
    later rewritten.
    """
    long_call = Metrics(
        max_profit=None,
        max_loss=-344.05,
        breakevens=[25544.05],
        net_premium=344.05,
        reward_risk=None,
    )
    dumped = long_call.model_dump_json()

    assert '"max_profit":null' in dumped
    assert '"reward_risk":null' in dumped, "a ratio against an Unbounded gain has no meaning"
    assert not {"Infinity", "-Infinity", "NaN"} & set(dumped.split(",")), dumped

    for poison in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValidationError):
            Metrics(
                max_profit=poison,
                max_loss=-344.05,
                breakevens=[25544.05],
                net_premium=344.05,
                reward_risk=None,
            )


def test_one_response_carries_the_whole_answer_and_the_curve_cannot_be_ragged():
    """#24: metrics come back 'from one call rather than several'.

    The endpoint is deliberately fat. Splitting it would mean several round trips
    carrying the same Legs and recomputing the same curve, and the trader would watch
    the numbers arrive after the chart they belong to.

    The curve is two parallel arrays, which is the shape the prototype in #9 published
    and the shape a chart consumes. Parallel arrays can disagree in length, and a curve
    that is one point short does not raise - it draws, slightly wrong. So the type will
    not hold a ragged one.
    """
    exposure = LegGreeks(delta=0.5121, gamma=0.0002, vega=19.87, theta=-8.34, rho=4.12)
    response = AnalysisResponse(
        moment="2026-01-27T06:30:00",
        spot=25100.25,
        forward=25219.12,
        discount=0.993480,
        curve=Curve(spot=[24000.0, 25200.0, 26000.0], pnl_at_expiry=[-344.05, -344.05, 455.95]),
        metrics=Metrics(
            max_profit=None,
            max_loss=-344.05,
            breakevens=[25544.05],
            net_premium=344.05,
            reward_risk=None,
        ),
        greeks=[exposure],
        total_greeks=exposure,
    )
    assert {"curve", "metrics", "greeks", "total_greeks"} <= set(response.model_dump())
    assert len(response.curve.spot) == len(response.curve.pnl_at_expiry)

    # The Forward is published beside the Greeks because a delta is a slope against
    # something, and that something is not spot: the two differ by 118.87 here (#51).
    assert response.forward - response.spot == pytest.approx(118.87, abs=0.01)

    # A Greek is a Finite like every other number on the wire - ADR-0001 bans NaN on it
    # as firmly as it bans one in a metric.
    with pytest.raises(ValidationError):
        LegGreeks(delta=float("nan"), gamma=0.0, vega=0.0, theta=0.0, rho=0.0)

    with pytest.raises(ValidationError):
        Curve(spot=[24000.0, 25200.0], pnl_at_expiry=[-344.05])

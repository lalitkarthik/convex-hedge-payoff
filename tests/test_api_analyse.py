"""Seam one: the HTTP boundary. **This is the primary seam** (#23).

Everything a trader can observe passes through it, so it covers the Chain, Strategy and
shared-type modules without importing any of them. There are deliberately **no unit
tests on the Strategy module**: a Breakeven bug surfaces identically here, with a slower
feedback loop, in exchange for tests that do not have to be rewritten when the internals
move.

So these assert what a caller receives, never that a particular helper was called.

The anchor moment throughout is **2026-01-27 06:30 UTC = 12:00 IST**, the minute the
prototype in #9 was measured at. At that minute the 25200 call last traded at 344.05 and
the 25200 put at 326.70 - a straddle premium of 670.75 per unit, which is where every
number in this file comes from.
"""

import pytest
from fastapi.testclient import TestClient

from payoff.api import app

MOMENT = "2026-01-27T06:30:00"
STRIKE = 25200.0
STRADDLE_PREMIUM = 670.75
"""344.05 + 326.70, read off the Chain at the anchor moment."""


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def analyse(client: TestClient, legs: list[dict], **extra):
    return client.post("/analyse", json={"moment": MOMENT, "legs": legs, **extra})


def test_a_single_bought_call_comes_back_as_a_payoff_curve(client):
    """#24's tracer bullet: 'a curve of at least 200 points, each a Spot and a P&L'.

    The Leg is described by strike, type and direction alone. The client supplies no
    price and no volatility - the server reads both off the Chain at the moment asked
    for, which is what makes this an analysis of the market rather than of whatever the
    caller happened to send.
    """
    response = analyse(client, [{"strike": STRIKE, "option_type": "CE", "direction": 1}])
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["spot"] == pytest.approx(25100.25), "the NIFTY level at the anchor minute"

    curve = body["curve"]
    assert len(curve["spot"]) >= 200
    assert len(curve["pnl_at_expiry"]) == len(curve["spot"])
    assert curve["spot"] == sorted(curve["spot"]), "an x-axis that is not sorted is not an axis"


SHORT_STRADDLE = [
    {"strike": STRIKE, "option_type": "CE", "direction": -1},
    {"strike": STRIKE, "option_type": "PE", "direction": -1},
]
LONG_STRADDLE = [{**leg, "direction": 1} for leg in SHORT_STRADDLE]


def test_a_short_straddle_reports_the_prototypes_breakevens_exactly(client):
    """#24: 'Breakevens of 24529.25 and 25870.75, matching the prototype exactly.'

    Exactly, not approximately: a straddle breaks even at the strike plus and minus the
    Net Premium per unit, and 25200 -/+ 670.75 is a property a trader depends on rather
    than a number that came out of a fit. A scan across the curve gets this wrong in the
    third decimal, which is how you find out you have written one.
    """
    metrics = analyse(client, SHORT_STRADDLE).json()["metrics"]

    assert metrics["breakevens"] == pytest.approx([24529.25, 25870.75], abs=1e-6)
    assert metrics["breakevens"] == pytest.approx(
        [STRIKE - STRADDLE_PREMIUM, STRIKE + STRADDLE_PREMIUM], abs=1e-6
    )


def test_a_short_straddle_caps_its_gain_at_the_premium_it_received(client):
    """670.75 per unit at the strike - and which side of the ledger it falls on.

    #24 calls this a Max **Loss**; #29 calls the same position's figure a Max
    **Profit**. The data settles it. At the anchor minute the 25200 call last traded at
    344.05 and the put at 326.70, so a *short* straddle receives 670.75 as a credit and
    that credit is the most it can make, while its downside runs with the market. The
    same 670.75 is the *long* straddle's maximum loss, which is the figure
    CONTRIBUTING.md records. #24's bullet has the word wrong.

    Asserted in both directions so the ambiguity cannot survive.
    """
    short = analyse(client, SHORT_STRADDLE).json()["metrics"]
    assert short["max_profit"] == pytest.approx(STRADDLE_PREMIUM, abs=1e-6)
    assert short["max_loss"] is None, "a short straddle's downside is Unbounded"
    assert short["net_premium"] == pytest.approx(-STRADDLE_PREMIUM, abs=1e-6), "a credit"

    long = analyse(client, LONG_STRADDLE).json()["metrics"]
    assert long["max_loss"] == pytest.approx(-STRADDLE_PREMIUM, abs=1e-6)
    assert long["max_profit"] is None
    assert long["net_premium"] == pytest.approx(STRADDLE_PREMIUM, abs=1e-6), "a debit"
    assert long["breakevens"] == pytest.approx([24529.25, 25870.75], abs=1e-6), (
        "Breakevens are a property of the Legs and do not care which way they are held"
    )


IRON_CONDOR = [
    {"strike": 24800.0, "option_type": "PE", "direction": 1},
    {"strike": 25000.0, "option_type": "PE", "direction": -1},
    {"strike": 25400.0, "option_type": "CE", "direction": -1},
    {"strike": 25600.0, "option_type": "CE", "direction": 1},
]


def test_one_leg_and_four_legs_go_down_the_same_path(client):
    """#24: 'metrics computed from the list of Legs with no branching on leg count or
    Strategy name'.

    An iron condor is four Legs; a naked call is one. Neither the request nor the
    response says which, and nothing in between recognises the shape - which is what
    makes #30's Presets add no engine code at all.

    Both of the condor's wings are bought, so both tails terminate and nothing is
    Unbounded. That is also the only shape in which Reward/Risk means anything: a ratio
    against an Unlimited gain has none.
    """
    condor = analyse(client, IRON_CONDOR)
    assert condor.status_code == 200, condor.text
    metrics = condor.json()["metrics"]

    assert metrics["max_profit"] is not None
    assert metrics["max_loss"] is not None
    assert len(metrics["breakevens"]) == 2
    assert metrics["reward_risk"] == pytest.approx(
        metrics["max_profit"] / abs(metrics["max_loss"]), rel=1e-9
    )

    naked = analyse(client, [{"strike": STRIKE, "option_type": "CE", "direction": 1}])
    assert naked.status_code == 200
    assert set(naked.json()) == set(condor.json()), "one shape of response, whatever the shape"
    assert set(naked.json()["metrics"]) == set(metrics)


def test_an_unbounded_figure_is_json_null_and_never_an_infinity_token(client):
    """#24: 'never an infinity token or a string'. JSON has no infinity.

    ADR-0001's ban on NaN is held all the way to the wire, for the same reason it holds
    in the core: a NaN renders as an invisible gap in a chart and survives review.
    """
    response = analyse(client, [{"strike": STRIKE, "option_type": "CE", "direction": 1}])
    metrics = response.json()["metrics"]

    assert metrics["max_profit"] is None
    assert metrics["reward_risk"] is None
    assert metrics["max_loss"] == pytest.approx(-344.05, abs=1e-6), "capped at what it cost"

    for legs in ([{"strike": STRIKE, "option_type": "CE", "direction": 1}], SHORT_STRADDLE):
        text = analyse(client, legs).text
        assert not {"Infinity", "-Infinity", "NaN", "nan", "1e999"} & set(
            text.replace("[", ",").replace("]", ",").replace("{", ",").replace("}", ",").split(",")
        ), text


def test_the_client_cannot_smuggle_implied_volatility_over_the_wire(client):
    """#23: the server looks volatility up. Asserted at the boundary, not only at the
    type - a caller experiences the rule as a 422, not as a field that quietly vanishes.
    """
    response = analyse(
        client, [{"strike": STRIKE, "option_type": "CE", "direction": 1, "iv": 0.01}]
    )
    assert response.status_code == 422


def test_an_entry_premium_override_moves_the_breakevens(client):
    """Story 18: 'what if I had entered at X'. The one price a trader may supply.

    The Chain's price is the default, not a floor - overriding it moves the Breakeven
    with it, because a Breakeven is Payoff minus what was actually paid.
    """
    as_traded = analyse(
        client, [{"strike": STRIKE, "option_type": "CE", "direction": 1}]
    ).json()["metrics"]
    assert as_traded["breakevens"] == pytest.approx([25544.05], abs=1e-6), "25200 + 344.05"

    overridden = analyse(
        client,
        [{"strike": STRIKE, "option_type": "CE", "direction": 1, "entry_premium": 100.0}],
    ).json()["metrics"]
    assert overridden["breakevens"] == pytest.approx([25300.0], abs=1e-6), "25200 + 100"
    assert overridden["net_premium"] == pytest.approx(100.0, abs=1e-6)


GREEKS = ("delta", "gamma", "vega", "theta", "rho")


def test_the_greeks_come_back_with_the_curve_and_not_from_a_second_call(client):
    """#27, and #53's convention.

    `models.py` already records the intent - "#27 and #29 add the Greeks and the Payoff
    Table to this same response rather than to endpoints of their own" - so the test that
    matters is that one POST carries both. A trader who has to wait for a second request
    watches the exposures arrive after the chart they belong to.

    Published per **contract**: no lot size, no number of lots. #29 owns that multiplier,
    and keeping it out of here is what lets a Greek and a currency figure scale
    differently without either one branching.

    **Delta is discounted** (#53), which is why the bound below is `D` and not 1. At this
    minute D is 0.993480, so a bought at-the-money call cannot report more than that. An
    undiscounted convention would sit just above it - a difference of 1.26% on this day,
    large enough to matter and small enough to read as rounding.
    """
    response = analyse(client, [{"strike": STRIKE, "option_type": "CE", "direction": 1}])
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["forward"] == pytest.approx(25219.12, abs=0.01), "what they were priced at"
    assert body["discount"] == pytest.approx(0.993480, abs=1e-6)

    assert len(body["greeks"]) == 1, "one row per leg, in the order they were sent"
    leg = body["greeks"][0]
    assert set(leg) == set(GREEKS)

    assert 0.0 < leg["delta"] < body["discount"], "a call's delta is bounded by D, not by 1"
    assert leg["gamma"] > 0.0, "long options are gamma-positive, call or put alike"
    assert leg["vega"] > 0.0
    assert leg["theta"] < 0.0, "a bought option loses value as a session passes"

    assert body["total_greeks"] == leg, "one leg, so the total is that leg"


def test_selling_a_leg_negates_every_greek_it_reports(client):
    """#53: "a short leg reports the negated Greek of the equivalent long leg".

    The aggregation is `G = sum_i d_i q_i g_i` - direction and quantity multiply in, with
    no branching on leg count and none on Strategy name. This is the cheapest test of
    that: the same contract, the other way round.

    Asserted exactly rather than approximately. The two differ by a sign applied to one
    float, so anything other than exact negation means a second calculation crept in.
    """
    long = analyse(client, [{"strike": STRIKE, "option_type": "PE", "direction": 1}]).json()
    short = analyse(client, [{"strike": STRIKE, "option_type": "PE", "direction": -1}]).json()

    for greek in GREEKS:
        assert short["greeks"][0][greek] == -long["greeks"][0][greek], greek


def test_the_total_is_the_sum_of_the_legs_and_a_straddle_is_delta_flat(client):
    """A short straddle at the money: the two deltas very nearly cancel.

    Not exactly - the money is the strike nearest the **forward** (25,200 against a
    forward of 25,219.12), so the call is a shade in the money and the put a shade out,
    and the residual is real rather than an error. Asserting it is zero would be
    asserting a coincidence.

    What is exact is that the total is the sum: a Strategy's exposure is a property of
    its Legs and nothing else.
    """
    body = analyse(
        client,
        [
            {"strike": STRIKE, "option_type": "CE", "direction": -1},
            {"strike": STRIKE, "option_type": "PE", "direction": -1},
        ],
    ).json()

    assert len(body["greeks"]) == 2
    for greek in GREEKS:
        assert body["total_greeks"][greek] == pytest.approx(
            sum(leg[greek] for leg in body["greeks"]), abs=1e-12
        ), greek

    assert abs(body["total_greeks"]["delta"]) < 0.05, "sold straddle: nearly delta flat"
    assert body["total_greeks"]["gamma"] < 0.0, "and short gamma, which is the risk in it"
    assert body["total_greeks"]["theta"] > 0.0, "the compensation for carrying it"

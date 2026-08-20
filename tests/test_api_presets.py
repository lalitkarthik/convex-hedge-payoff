"""Seam one: Presets.

**This ticket adds no engine code, and that is the point** (#30). A Preset is a
function returning a list of Legs. Every metric is already computed from a list of Legs
with no knowledge of what it is called, so an iron condor goes down exactly the path a
naked call does. If a Preset had needed a change in `strategy.py`, something earlier
was built wrong - that is the tripwire this ticket exists to trip.

So the tests here assert **behaviour a trader depends on**, never shape. #23 names this
as the clearest case of good versus bad testing: asserting that a straddle produces two
Legs at the same strike tests an implementation detail, whereas asserting that its two
Breakevens sit either side of the strike at the Net Premium distance tests the thing a
trader would notice being wrong. The second kind survives any refactor that preserves
the numbers.

The anchor moment is 2026-01-27 06:30 UTC = 12:00 IST. Spot is 25100.25 there, so the
at-the-money strike is 25100.
"""

import pytest
from fastapi.testclient import TestClient

from payoff.api import app

MOMENT = "2026-01-27T06:30:00"
ATM = 25100.0

FIVE = {"straddle", "strangle", "iron_condor", "credit_spread", "iron_fly"}


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def test_the_picker_offers_five_presets(client):
    """Story 17: a short list, so a structure that would take four picks takes one."""
    response = client.get("/presets")
    assert response.status_code == 200, response.text

    assert set(response.json()["presets"]) == FIVE


def build(client: TestClient, name: str, **params) -> list[dict]:
    """Ask for a Preset's Legs, exactly as the picker would."""
    response = client.get(f"/presets/{name}", params={"moment": MOMENT, **params})
    assert response.status_code == 200, response.text
    return response.json()["legs"]


def analyse(client: TestClient, legs: list[dict]) -> dict:
    """Analyse a list of Legs through the one endpoint every Strategy goes through."""
    response = client.post("/analyse", json={"moment": MOMENT, "legs": legs})
    assert response.status_code == 200, response.text
    return response.json()


def test_a_straddles_breakevens_sit_a_net_premium_either_side_of_its_strike(client):
    """The identity a trader depends on, rather than two magic numbers.

    #23 uses exactly this as the example of a good test: asserting a straddle produces
    two Legs at one strike tests an implementation detail, while asserting where its
    Breakevens land tests what a trader would notice being wrong. This survives any
    refactor that preserves the maths.

    At the anchor strike the identity produces #24's published figures, so the two
    readings agree: 25200 -/+ 670.75 is 24529.25 and 25870.75.
    """
    metrics = analyse(client, build(client, "straddle", strike=25200.0))["metrics"]

    premium = abs(metrics["net_premium"])
    assert metrics["breakevens"] == pytest.approx([25200.0 - premium, 25200.0 + premium])
    assert metrics["breakevens"] == pytest.approx([24529.25, 25870.75], abs=1e-6)
    assert premium == pytest.approx(670.75, abs=1e-6)


def test_a_preset_defaults_to_the_money(client):
    """Story 17 is about saving picks, so the common case needs no parameters at all.

    Spot is 25100.25 at the anchor minute and the chain is on a 50-point grid, so the
    nearest strike is 25100. "Nearest quoted strike" rather than "spot rounded": on a
    thin minute the arithmetic answer may not be quoted at all.
    """
    metrics = analyse(client, build(client, "straddle"))["metrics"]

    premium = abs(metrics["net_premium"])
    assert metrics["breakevens"] == pytest.approx([ATM - premium, ATM + premium])


def test_an_iron_condor_is_four_legs_down_the_same_path_as_one(client):
    """#30's real acceptance criterion, and the architecture test underneath it.

    Both wings are bought, so both tails terminate and nothing is Unbounded - which is
    also the only shape where Reward/Risk means anything. The credit received is the
    most the position can make, because it keeps all of it only if Expiry lands inside
    the body.

    A naked call gets the same response, field for field: nothing between the request
    and the answer knows how many Legs there were or what the shape is called.
    """
    condor = analyse(client, build(client, "iron_condor"))
    metrics = condor["metrics"]

    assert metrics["max_profit"] is not None
    assert metrics["max_loss"] is not None
    assert metrics["net_premium"] < 0, "a short condor is a credit"
    assert metrics["max_profit"] == pytest.approx(abs(metrics["net_premium"]), abs=1e-9)

    low, high = metrics["breakevens"]
    assert low < ATM < high, "the body straddles the money"
    assert metrics["reward_risk"] == pytest.approx(
        metrics["max_profit"] / abs(metrics["max_loss"]), rel=1e-9
    )

    naked = analyse(client, [{"strike": ATM, "option_type": "CE", "direction": 1}])
    assert set(naked) == set(condor)
    assert set(naked["metrics"]) == set(metrics)


def test_choosing_a_preset_is_the_same_as_picking_its_legs_by_hand(client):
    """#30: 'analysing a Preset produces the same result as selecting its Legs by hand'.

    Not "agrees to a tolerance" - the same response. A Preset hands back exactly what a
    trader would have picked, and it goes through the one analysis endpoint, so there
    is no second path that could drift from the first.
    """
    by_preset = analyse(client, build(client, "iron_condor", strike=25100.0, width=200.0))
    by_hand = analyse(
        client,
        [
            {"strike": 24900.0, "option_type": "PE", "direction": -1},
            {"strike": 24700.0, "option_type": "PE", "direction": 1},
            {"strike": 25300.0, "option_type": "CE", "direction": -1},
            {"strike": 25500.0, "option_type": "CE", "direction": 1},
        ],
    )
    assert by_preset == by_hand


def test_a_bought_strangle_risks_only_its_premium_and_keeps_its_upside(client):
    """Cheaper than a straddle and needs a bigger move - the trade-off a trader makes.

    Both Breakevens sit **outside** the two strikes, which is what distinguishes a
    strangle from the straddle it is a spread-out version of: between them both Legs
    expire worthless and the loss is the whole premium.

    Bought, the upside is Unbounded and serialises as null. The downside is not: Spot
    cannot fall below zero, so the left tail always terminates (CONTEXT.md).
    """
    metrics = analyse(client, build(client, "strangle", strike=25100.0, width=200.0))["metrics"]
    low, high = metrics["breakevens"]

    assert low < 24900.0 < 25300.0 < high, "outside the two strikes, not between them"
    assert metrics["max_profit"] is None, "a bought call above the upper strike runs"
    assert metrics["max_loss"] == pytest.approx(-metrics["net_premium"], abs=1e-9)
    assert metrics["net_premium"] > 0, "a debit"
    assert high - low > 25870.75 - 24529.25, "wider than the straddle at the same centre"


def test_a_credit_spread_is_capped_on_both_sides_and_breaks_even_once(client):
    """The one directional Preset: paid up front, with the loss bounded by the far Leg.

    Exactly one Breakeven, because the payoff crosses zero once - which is what makes
    it a directional trade rather than a view on movement. Max Profit is the credit
    itself, and Max Loss is the distance between the strikes less that credit, so the
    two must sum to the width. A put spread is the bullish one: it profits while Spot
    stays above the sold strike.
    """
    spread = build(client, "credit_spread", strike=25100.0, width=200.0)
    metrics = analyse(client, spread)["metrics"]

    assert metrics["net_premium"] < 0, "received, not paid"
    assert metrics["max_profit"] == pytest.approx(abs(metrics["net_premium"]), abs=1e-9)
    assert metrics["max_loss"] is not None, "the bought Leg is what bounds it"
    assert metrics["max_profit"] - metrics["max_loss"] == pytest.approx(200.0, abs=1e-9), (
        "credit plus risk is the width between the strikes"
    )

    assert len(metrics["breakevens"]) == 1
    assert 24900.0 < metrics["breakevens"][0] < 25100.0


def test_an_iron_fly_keeps_the_condors_shape_with_its_body_closed(client):
    """A short straddle with wings bought: the condor's body squeezed to a point.

    It earns more than the condor at the same width, because a sold straddle collects
    more than a sold strangle - and it earns it over a narrower range, which is the
    trade. Both wings are bought, so both tails terminate and Reward/Risk means
    something.
    """
    fly = analyse(client, build(client, "iron_fly", strike=25100.0, width=200.0))["metrics"]
    condor = analyse(client, build(client, "iron_condor", strike=25100.0, width=200.0))["metrics"]

    assert fly["net_premium"] < 0, "a credit"
    assert fly["max_profit"] == pytest.approx(abs(fly["net_premium"]), abs=1e-9)
    assert fly["max_loss"] is not None

    low, high = fly["breakevens"]
    assert low < ATM < high
    assert fly["max_profit"] > condor["max_profit"], "a sold straddle collects more"
    assert high - low < condor["breakevens"][1] - condor["breakevens"][0], "over a narrower range"


def test_a_presets_legs_are_ordinary_legs_and_stop_matching_it_when_edited(client):
    """CONTEXT.md: 'a Preset produces a Strategy; it is not a kind of Strategy.'

    Nothing stores "this is an iron condor", so removing a Leg does not invalidate
    anything - it just makes a three-Leg Strategy, which analyses like any other. This
    is the server-side half of #30's "editable and removable afterwards"; the controls
    themselves are the UI half.

    Removing a bought wing is the sharpest version: the structure that had a bounded
    loss now has an Unbounded one, and the engine says so rather than refusing.
    """
    legs = build(client, "iron_condor", strike=25100.0, width=200.0)
    assert analyse(client, legs)["metrics"]["max_loss"] is not None

    bought_call = {"option_type": "CE", "direction": 1}
    without_a_wing = [
        leg for leg in legs if not all(leg[key] == value for key, value in bought_call.items())
    ]
    edited = analyse(client, without_a_wing)["metrics"]
    assert edited["max_loss"] is None, "the sold call now runs uncovered"
    assert edited["reward_risk"] is None

    heavier = analyse(client, [{**leg, "quantity": 3} for leg in legs])["metrics"]
    assert heavier["net_premium"] == pytest.approx(
        3 * analyse(client, legs)["metrics"]["net_premium"], abs=1e-9
    )


def test_a_name_the_picker_does_not_offer_is_not_found(client):
    """The picker only ever sends names from /presets, so this is a typed URL or a
    stale bookmark. #31 owns what the body of an error looks like; the status is here
    because a 500 would say the server broke, and it did not.
    """
    response = client.get("/presets/butterfly", params={"moment": MOMENT})
    assert response.status_code == 404

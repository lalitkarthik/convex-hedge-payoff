"""The Expiry line, at its corners. **#70**, on the primary seam.

A Payoff is flat, then straight, and bends exactly once, so three points describe one
Leg's exactly. `scripts/build_runtime.py` stores those three per contract and the serving
path interpolates between them, which is exact because the function genuinely is straight
in between - unlike a sampled grid, which stores the same segment over and over and still
cuts the corner unless a sample lands precisely on the strike.

**Everything here is asserted at a corner**, and that is the point rather than an economy
of effort. Away from the corners a wrong implementation agrees with a right one: the line
is straight, so any two points on it interpolate to the same place. The corners are the
only Forwards where a shared-domain mistake has anywhere to show, and even there it shows
as a plausible number rather than as an exception. Four Legs, four corners, four chances
to be quietly wrong - which is the failure that once reported a two-Leg delta of -157
where the true figure was +742.

So the expected values below are computed from strike, type, direction and premium, in
this file, by hand. Reading them back off the same store the engine read them from would
assert that a number equals itself.

The anchor moment is 2026-01-27 06:30 UTC = 12:00 IST, as everywhere else in the suite.
"""

import pytest
from fastapi.testclient import TestClient

from payoff.api import app

MOMENT = "2026-01-27T06:30:00"

EXPIRY = "10FEB26"
"""The dataset's one series, named on every Leg because a Leg carries its own (#71)."""

IRON_CONDOR = [
    {"strike": 24800.0, "option_type": "PE", "expiry": EXPIRY, "direction": 1},
    {"strike": 25000.0, "option_type": "PE", "expiry": EXPIRY, "direction": -1},
    {"strike": 25400.0, "option_type": "CE", "expiry": EXPIRY, "direction": -1},
    {"strike": 25600.0, "option_type": "CE", "expiry": EXPIRY, "direction": 1},
]

PREMIUMS = {
    (24800.0, "PE"): 180.10,
    (25000.0, "PE"): 245.00,
    (25400.0, "CE"): 250.35,
    (25600.0, "CE"): 173.60,
}
"""What each Leg last traded at on the Chain at the anchor minute.

Spelled out rather than read off the response, so that the arithmetic below is a check on
the engine rather than a restatement of it. The four sum, with direction, to a credit of
141.65: `-180.10 + 245.00 + 250.35 - 173.60`.
"""

CORNERS = (24800.0, 25000.0, 25400.0, 25600.0)
"""The four strikes - and therefore the four Forwards at which this Strategy bends."""

CREDIT = 141.65
"""The Net Premium received, which for a short condor is also its Max Profit."""

WIDE = [
    {"strike": 24000.0, "option_type": "CE", "expiry": EXPIRY, "direction": 1},
    {"strike": 25000.0, "option_type": "CE", "expiry": EXPIRY, "direction": -1},
    {"strike": 25400.0, "option_type": "PE", "expiry": EXPIRY, "direction": -1},
    {"strike": 26400.0, "option_type": "PE", "expiry": EXPIRY, "direction": 1},
]
"""A four-Leg Strategy whose corners are 2,400 points apart, and the reason it is here.

The iron condor's four strikes span 800 points, which is close enough together that a
Leg's own strike is within a few per cent of every other Leg's. A per-Leg domain of any
plausible width - the chart's own +/-6%, say - would still reach all four corners, so the
sum would come out right and the mistake would go unseen.

These four do not let it. A bought 24,000 call read at the 26,400 corner is 2,400 points
in the money, which is 10% above its own strike, and a sold 26,400 put read at the 24,000
corner is 2,400 points the other way. A Leg carrying its own domain has to clamp at both,
and clamping an in-the-money Payoff is where the shape goes wrong.

Deep calls and deep puts do not trade, so the strikes are picked from what is actually
quoted at the anchor minute: 23,500 is the lowest call and 27,150 the highest put.
"""

WIDE_PREMIUMS = {
    (24000.0, "CE"): 1275.00,
    (25000.0, "CE"): 459.25,
    (25400.0, "PE"): 429.90,
    (26400.0, "PE"): 1201.20,
}
"""A net debit of 1,587.05: `1275.00 - 459.25 - 429.90 + 1201.20`."""

WIDE_CORNERS = (24000.0, 25000.0, 25400.0, 26400.0)


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def analyse(client: TestClient, legs: list[dict]) -> dict:
    response = client.post("/analyse", json={"moment": MOMENT, "legs": legs})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture(scope="module")
def condor(client: TestClient) -> dict:
    return analyse(client, IRON_CONDOR)


def payoff(forward: float, leg: dict) -> float:
    """`max(F - K, 0)` for a call, `max(K - F, 0)` for a put. Premium-blind (CONTEXT.md)."""
    if leg["option_type"] == "CE":
        return max(forward - leg["strike"], 0.0)
    return max(leg["strike"] - forward, 0.0)


def pnl(forward: float, legs: list[dict], premiums: dict = PREMIUMS) -> float:
    """What the whole Strategy is worth at one Forward, from the Legs and nothing else."""
    return sum(
        leg["direction"] * (payoff(forward, leg) - premiums[(leg["strike"], leg["option_type"])])
        for leg in legs
    )


def drawn(body: dict) -> dict[float, float]:
    return dict(zip(body["curve"]["spot"], body["curve"]["pnl_at_expiry"]))


def on_the_line(body: dict, forward: float) -> float:
    """The drawn line's value at `forward`, read the way a chart reads it.

    Linear interpolation between the two points either side, which is what a chart draws
    between two vertices and therefore what a trader's eye reads off it.
    """
    points = sorted(zip(body["curve"]["spot"], body["curve"]["pnl_at_expiry"]))
    below = max(point for point in points if point[0] <= forward)
    above = min(point for point in points if point[0] >= forward)
    if above[0] == below[0]:
        return below[1]
    slope = (above[1] - below[1]) / (above[0] - below[0])
    return below[1] + slope * (forward - below[0])


def test_every_corner_of_a_four_leg_strategy_is_a_point_on_the_line(condor):
    """A kink the chart does not visit is a kink the chart rounds off.

    Four hundred evenly spaced points across +/-6% land 7.55 apart on this chain, so
    three of these four strikes fall strictly between two samples and the fourth would
    only land on one by luck. Whatever the sampling, the corner has to be there.
    """
    curve = drawn(condor)

    for corner in CORNERS:
        assert corner in curve, f"the line does not pass through its own corner at {corner}"

    spots = condor["curve"]["spot"]
    assert spots == sorted(spots), "an x-axis that is not sorted is not an axis"
    assert len(spots) == len(set(spots)), "a Forward drawn twice is a Forward drawn twice"


def test_the_four_leg_sum_is_exact_at_each_of_its_four_corners(condor):
    """**The assertion this ticket exists for.**

    Legs are summed by adding their values at the same Forward. If each Leg's corners sat
    on a domain centred on its own strike, every Leg would still look right on its own -
    a bought put still bends at its strike, still runs at 45 degrees below it - and the
    sum would be wrong at every corner but the one belonging to the Leg being looked at.
    A four-Leg structure would come back with four wrong vertices and a shape a trader
    would accept, because a condor with the wrong shoulders is still condor-shaped.

    Exact to 1e-9, not approximate: both sides are the same arithmetic on the same
    floats, and a stored corner is a stored number rather than a fitted one. A tolerance
    here would be room for exactly the error being ruled out.
    """
    curve = drawn(condor)

    for corner in CORNERS:
        assert curve[corner] == pytest.approx(pnl(corner, IRON_CONDOR), abs=1e-9), corner

    # And the same four numbers written out, so the arithmetic above is checkable by eye:
    # inside the body both sold Legs expire worthless and the credit is kept whole; at a
    # sold strike the body is 200 points from the bought wing, so the credit less that
    # width is what is left.
    assert curve[25000.0] == pytest.approx(CREDIT, abs=1e-9)
    assert curve[25400.0] == pytest.approx(CREDIT, abs=1e-9)
    assert curve[24800.0] == pytest.approx(CREDIT - 200.0, abs=1e-9)
    assert curve[25600.0] == pytest.approx(CREDIT - 200.0, abs=1e-9)


def test_corners_far_apart_sum_correctly_and_are_not_clamped_to_a_leg_of_their_own(client):
    """The same claim with the Legs pushed apart until a per-Leg domain cannot hide.

    2,400 points between the outer corners, which is 10% of a strike - wider than any
    per-Leg window anybody would pick, including the +/-6% the chart itself uses. A Leg
    holding its own domain would clamp at the far corner, and clamping an **in-the-money**
    Payoff is where the number changes: the bought 24,000 call is worth 2,400 at the
    26,400 corner and a domain ending at 25,440 would report 1,440 of it.

    Every corner, and both single-Leg reads at each, so the error has nowhere to cancel.
    """
    wide = analyse(client, WIDE)
    curve = drawn(wide)

    for corner in WIDE_CORNERS:
        assert corner in curve, f"the line does not pass through its own corner at {corner}"
        assert curve[corner] == pytest.approx(pnl(corner, WIDE, WIDE_PREMIUMS), abs=1e-9), corner

    for leg in WIDE:
        alone = analyse(client, [leg])
        for corner in WIDE_CORNERS:
            assert on_the_line(alone, corner) == pytest.approx(
                pnl(corner, [leg], WIDE_PREMIUMS), abs=1e-9
            ), f"{leg['strike']:.0f} {leg['option_type']} is wrong at {corner:.0f}"

    # Flat at both ends and a plateau between the two sold strikes: a debit of 1,587.05
    # against 2,000 points of intrinsic value collected at the corners.
    assert curve[24000.0] == pytest.approx(-587.05, abs=1e-9)
    assert curve[26400.0] == pytest.approx(-587.05, abs=1e-9)
    assert curve[25000.0] == pytest.approx(412.95, abs=1e-9)
    assert curve[25400.0] == pytest.approx(412.95, abs=1e-9)

    assert wide["metrics"]["max_profit"] == pytest.approx(max(curve.values()), abs=1e-9)
    assert wide["metrics"]["max_loss"] == pytest.approx(min(curve.values()), abs=1e-9)


def test_each_leg_is_valued_at_the_other_legs_corners_and_not_only_at_its_own(client):
    """The shared domain, taken apart Leg by Leg.

    The sum being right could in principle survive two errors that cancel, so the four
    Legs are also analysed one at a time and each is read at **all four** corners - three
    of which are somebody else's. A Leg whose stored corners were centred on its own
    strike would be clamped flat at another Leg's, because interpolation outside the
    points it holds cannot do anything else, and that is the shape of the error.
    """
    for leg in IRON_CONDOR:
        alone = analyse(client, [leg])
        for corner in CORNERS:
            assert on_the_line(alone, corner) == pytest.approx(pnl(corner, [leg]), abs=1e-9), (
                f"{leg['strike']:.0f} {leg['option_type']} is wrong at {corner:.0f}"
            )


def test_the_published_extrema_are_the_extrema_of_the_line_that_is_drawn(condor):
    """#64 story 16: the number and the picture cannot disagree.

    Both wings are bought, so both tails terminate and neither figure is Unbounded - which
    is what makes this shape the one where the claim is checkable at all. The maximum and
    minimum of the drawn line are read straight off it and must be the two figures printed
    beside it, to the last decimal.
    """
    curve = drawn(condor)
    metrics = condor["metrics"]

    assert metrics["max_profit"] == pytest.approx(max(curve.values()), abs=1e-9)
    assert metrics["max_loss"] == pytest.approx(min(curve.values()), abs=1e-9)

    assert metrics["max_profit"] == pytest.approx(CREDIT, abs=1e-9), "the credit, kept whole"
    assert metrics["max_loss"] == pytest.approx(CREDIT - 200.0, abs=1e-9), "less the width"

    peaks = [spot for spot, value in curve.items() if value == metrics["max_profit"]]
    assert set(peaks) <= set(CORNERS) | {spot for spot in curve if 25000.0 < spot < 25400.0}, (
        "the maximum of a piecewise-linear curve sits on a corner or on the flat between two"
    )


def test_each_published_breakeven_is_a_forward_at_which_the_drawn_line_is_zero(condor):
    """The third figure read off the same shape.

    A Breakeven is solved between two corners rather than searched for on a grid, so it
    lands on a Forward no sample visits. What must hold is that the line the chart draws
    is zero there - if the two came from different shapes, the published level would sit
    a little to one side of where the line actually crosses, which is visible on a chart
    and impossible to explain.
    """
    low, high = condor["metrics"]["breakevens"]

    assert low == pytest.approx(25000.0 - CREDIT, abs=1e-9), "the sold put, less the credit"
    assert high == pytest.approx(25400.0 + CREDIT, abs=1e-9), "the sold call, plus the credit"

    for breakeven in (low, high):
        assert on_the_line(condor, breakeven) == pytest.approx(0.0, abs=1e-9)


def test_an_empty_strategy_still_draws_a_flat_line_on_the_shared_domain(client):
    """No Legs is what the page opens in, and it has no corners of its own.

    The domain's two ends still come from the manifest, so the line has an axis and the
    extrema have something to be a maximum of. A `None` or an empty array here would make
    every consumer branch on emptiness, and one of them would forget.
    """
    body = analyse(client, [])

    assert body["curve"]["spot"], "an empty Strategy still has a Forward axis"
    assert set(body["curve"]["pnl_at_expiry"]) == {0.0}
    assert body["metrics"]["breakevens"] == [], "flat at zero is not a Breakeven everywhere"

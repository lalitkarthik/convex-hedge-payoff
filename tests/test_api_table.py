"""The Payoff Table, on the same seam and in the same response as the chart.

Part of **#29**, taken early. Its lot-size half is untouched; what is here is the table
itself, and it is here because the frontend was computing it in TypeScript. That second
implementation is what ADR-0001 and the golden test exist to prevent, and the only
honest way to delete it is for the server to publish the rows.

**One computation, two presentations.** The chart and the table are the same P&L at
Expiry sampled on two grids - 400 points across +/-6% for the line, 50-point steps for
the rows a trader reads. If they can disagree, one of them is lying, and the assertion
that they agree at shared Spots is the whole reason the table ships in the fat response
rather than from an endpoint of its own.

The anchor moment is 2026-01-27 06:30 UTC = 12:00 IST, where the 25200 straddle costs
670.75 per unit.
"""

import pytest
from fastapi.testclient import TestClient

from payoff.api import app

MOMENT = "2026-01-27T06:30:00"
STRIKE = 25200.0
STRADDLE_PREMIUM = 670.75
STEP = 50.0
"""The strike spacing on this chain, so the rows line up with strikes actually traded."""

SHORT_STRADDLE = [
    {"strike": STRIKE, "option_type": "CE", "direction": -1},
    {"strike": STRIKE, "option_type": "PE", "direction": -1},
]


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="module")
def straddle(client: TestClient) -> dict:
    response = client.post("/analyse", json={"moment": MOMENT, "legs": SHORT_STRADDLE})
    assert response.status_code == 200, response.text
    return response.json()


def test_the_table_arrives_with_the_chart_rather_than_after_it(straddle):
    """#23 keeps the response deliberately fat, and #29 adds the table to *this* one.

    A second round trip would carry the same Legs and recompute the same P&L, and the
    trader would watch the rows arrive after the chart they belong to.
    """
    assert "table" in straddle
    table = straddle["table"]
    assert len(table["spot"]) == len(table["pnl_at_expiry"])
    assert len(table["spot"]) > 10, "a table of three rows is not a table"


def test_the_rows_step_by_the_strike_spacing(straddle):
    """50 points, so every row is a strike a trader could actually have traded.

    An interval chosen for round numbers instead - 100, or the range over 30 - would put
    rows between strikes, and the table would stop being readable against the Chain
    beside it.
    """
    spots = straddle["table"]["spot"]
    assert spots == sorted(spots)

    steps = {round(b - a, 6) for a, b in zip(spots, spots[1:])}
    assert steps == {STEP}, f"expected a uniform {STEP}-point grid, got steps {sorted(steps)}"

    for spot in spots:
        assert spot % STEP == 0, f"{spot} is not on the {STEP}-point grid"


def test_the_table_lies_on_the_chart_everywhere_the_chart_is_straight(straddle):
    """**The assertion that justifies putting the table in this response.**

    Two grids over one computation. The grids do not intersect - 400 points across
    +/-6% land on 7.55-point spacings and the rows land on multiples of 50 - so equality
    at shared Spots would be vacuously true. What is asserted instead is stronger:
    between kinks the P&L is a straight line, so interpolating the curve must reproduce
    the row **exactly**, not approximately.

    Rows within one curve-step of a strike are excluded, and deliberately: that is the
    one place the two legitimately differ, and the next test is about why.
    """
    curve = sorted(zip(straddle["curve"]["spot"], straddle["curve"]["pnl_at_expiry"]))
    step = curve[1][0] - curve[0][0]

    checked = 0
    for spot, pnl in zip(straddle["table"]["spot"], straddle["table"]["pnl_at_expiry"]):
        if abs(spot - STRIKE) <= step or not curve[0][0] < spot < curve[-1][0]:
            continue
        below = max(point for point in curve if point[0] <= spot)
        above = min(point for point in curve if point[0] >= spot)
        slope = (above[1] - below[1]) / (above[0] - below[0])
        assert pnl == pytest.approx(below[1] + slope * (spot - below[0]), abs=1e-9), (
            f"row {spot} is not on the line the chart draws"
        )
        checked += 1

    assert checked > 20, "the exclusion window swallowed the test"


def test_the_table_lands_on_the_peak_the_chart_steps_past(straddle):
    """Where the two grids differ, and why the table is the one to trust there.

    A short straddle peaks exactly at its strike. The chart's 400 points step about 7.55
    apart and miss it, reporting ~668.59 at the nearest sample; the table lands on 25,200
    because 50 divides it, and reports 670.75. Both are correct samples of one curve -
    the chart is drawing a line, not claiming its vertices are extrema.

    This is why `metrics` reads its extrema off the kinks rather than off a grid, and it
    is worth pinning: the day someone "simplifies" the table to a resample of the curve,
    the peak a trader reads becomes wrong by two rupees and nothing looks broken.
    """
    curve = dict(zip(straddle["curve"]["spot"], straddle["curve"]["pnl_at_expiry"]))
    table = dict(zip(straddle["table"]["spot"], straddle["table"]["pnl_at_expiry"]))

    assert table[STRIKE] == pytest.approx(STRADDLE_PREMIUM, abs=1e-9)
    assert max(curve.values()) < STRADDLE_PREMIUM, "the chart is expected to miss the peak"
    assert straddle["metrics"]["max_profit"] == pytest.approx(table[STRIKE], abs=1e-9)


def test_the_short_straddle_peaks_at_the_premium_it_received(straddle):
    """670.75 at the strike, which is the number every other assertion in this suite
    is anchored to - and it lands on a row, because 25200 is on the 50-point grid.

    A table that stepped past its own peak would show a trader a maximum that is not the
    maximum, and the figure beside the chart would disagree with the rows beneath it.
    """
    table = dict(zip(straddle["table"]["spot"], straddle["table"]["pnl_at_expiry"]))

    assert STRIKE in table, "the strike itself must be a row"
    assert table[STRIKE] == pytest.approx(STRADDLE_PREMIUM, abs=1e-9)
    assert max(table.values()) == pytest.approx(STRADDLE_PREMIUM, abs=1e-9)
    assert straddle["metrics"]["max_profit"] == pytest.approx(STRADDLE_PREMIUM, abs=1e-9)


def test_the_table_crosses_zero_at_the_published_breakevens(straddle):
    """24,529.25 and 25,870.75 are not on a 50-point grid, so no row sits at zero.

    What must hold is that the sign changes between the rows either side of each - a
    table whose signs contradicted the Breakevens printed above it would be the kind of
    inconsistency a trader spots instantly and cannot explain.
    """
    rows = sorted(zip(straddle["table"]["spot"], straddle["table"]["pnl_at_expiry"]))

    crossings = [
        (low[0], high[0])
        for low, high in zip(rows, rows[1:])
        if low[1] * high[1] < 0
    ]
    assert len(crossings) == 2, "a straddle changes sign exactly twice"

    for breakeven, (low, high) in zip(straddle["metrics"]["breakevens"], crossings):
        assert low <= breakeven <= high, f"breakeven {breakeven} is not between {low} and {high}"


def test_an_empty_strategy_still_returns_a_table(client):
    """No Legs is a legitimate state - it is what the page opens in.

    The rows are all zero, which is correct and which renders. A `null` here would make
    every consumer branch on emptiness, and one of them would forget.
    """
    body = client.post("/analyse", json={"moment": MOMENT, "legs": []}).json()

    assert body["table"]["spot"], "an empty Strategy still has a Spot axis"
    assert set(body["table"]["pnl_at_expiry"]) == {0.0}

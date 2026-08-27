"""The Payoff Table, on the same seam and in the same response as the chart.

Part of **#29**, taken early. Its lot-size half is untouched; what is here is the table
itself, and it is here because the frontend was computing it in TypeScript. That second
implementation is what ADR-0001 and the golden test exist to prevent, and the only
honest way to delete it is for the server to publish the rows.

**One computation, two presentations.** The chart and the table are the same P&L at
Expiry sampled on two grids - 400 points across +/-6% for the line, plus its corners
since #70, and 50-point steps for the rows a trader reads. If they can disagree, one of
them is lying, and the assertion that they agree at shared Forwards is the whole reason
the table ships in the fat response rather than from an endpoint of its own.

Both grids are in **Forward** and the arrays say so (#72). They were called `spot` and
were centred on Spot; CONTEXT.md makes the Forward the unit of the chart's x-axis, and
the wire now agrees with it.

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

EXPIRY = "10FEB26"
"""The dataset's one series, named on every Leg because a Leg carries its own (#71)."""

SHORT_STRADDLE = [
    {"strike": STRIKE, "option_type": "CE", "expiry": EXPIRY, "direction": -1},
    {"strike": STRIKE, "option_type": "PE", "expiry": EXPIRY, "direction": -1},
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
    assert len(table["forward"]) == len(table["pnl_at_expiry"])
    assert len(table["forward"]) > 10, "a table of three rows is not a table"


def test_the_rows_step_by_the_strike_spacing(straddle):
    """50 points, so every row is a strike a trader could actually have traded.

    An interval chosen for round numbers instead - 100, or the range over 30 - would put
    rows between strikes, and the table would stop being readable against the Chain
    beside it.
    """
    rows = straddle["table"]["forward"]
    assert rows == sorted(rows)

    steps = {round(b - a, 6) for a, b in zip(rows, rows[1:])}
    assert steps == {STEP}, f"expected a uniform {STEP}-point grid, got steps {sorted(steps)}"

    for row in rows:
        assert row % STEP == 0, f"{row} is not on the {STEP}-point grid"


def test_the_table_lies_on_the_chart_everywhere_the_chart_is_straight(straddle):
    """**The assertion that justifies putting the table in this response.**

    Two grids over one computation. The grids do not intersect - 400 points across
    +/-6% land on 7.55-point spacings and the rows land on multiples of 50 - so equality
    at shared Forwards would be vacuously true. What is asserted instead is stronger:
    between kinks the P&L is a straight line, so interpolating the curve must reproduce
    the row **exactly**, not approximately.

    Rows within one curve-step of a strike are excluded, and deliberately: that is the
    one place the two legitimately differ, and the next test is about why.
    """
    curve = sorted(zip(straddle["curve"]["forward"], straddle["curve"]["pnl_at_expiry"]))
    step = curve[1][0] - curve[0][0]

    checked = 0
    for row, pnl in zip(straddle["table"]["forward"], straddle["table"]["pnl_at_expiry"]):
        if abs(row - STRIKE) <= step or not curve[0][0] < row < curve[-1][0]:
            continue
        below = max(point for point in curve if point[0] <= row)
        above = min(point for point in curve if point[0] >= row)
        slope = (above[1] - below[1]) / (above[0] - below[0])
        assert pnl == pytest.approx(below[1] + slope * (row - below[0]), abs=1e-9), (
            f"row {row} is not on the line the chart draws"
        )
        checked += 1

    assert checked > 20, "the exclusion window swallowed the test"


def test_the_chart_the_table_and_the_figure_land_on_the_same_peak(straddle):
    """**#70 closed the gap this test used to pin**, and the assertion is inverted.

    It read `max(curve.values()) < STRADDLE_PREMIUM`, with the comment "the chart is
    expected to miss the peak". It did miss it: a short straddle peaks exactly at its
    strike, and the chart's 400 evenly spaced points step about 7.55 apart, so the
    nearest sample reported ~668.59 while the table and the Max Profit beside it said
    670.75. Three honest numbers off one curve on two grids - and nothing a trader could
    be told about it that would stop it looking like a bug.

    #64 story 16 is "max profit, max loss and Breakeven read off the same shape the chart
    draws, so that the number and the picture cannot disagree", and #70 is where that is
    delivered: the Expiry line is drawn through the stored corner points as well as
    through the grid, so the strike is a **vertex of the line** rather than a Forward
    between two of its samples.

    The old assertion is not weakened here, it is replaced by a stronger one - equality
    where there used to be an inequality, and a kink that must be present on the line
    rather than one that must be absent.
    """
    curve = dict(zip(straddle["curve"]["forward"], straddle["curve"]["pnl_at_expiry"]))
    table = dict(zip(straddle["table"]["forward"], straddle["table"]["pnl_at_expiry"]))

    assert STRIKE in curve, "the kink is a point on the line, not a gap between two of them"
    assert curve[STRIKE] == pytest.approx(STRADDLE_PREMIUM, abs=1e-9)
    assert table[STRIKE] == pytest.approx(STRADDLE_PREMIUM, abs=1e-9)
    assert max(curve.values()) == pytest.approx(STRADDLE_PREMIUM, abs=1e-9)
    assert straddle["metrics"]["max_profit"] == pytest.approx(table[STRIKE], abs=1e-9)


def test_the_short_straddle_peaks_at_the_premium_it_received(straddle):
    """670.75 at the strike, which is the number every other assertion in this suite
    is anchored to - and it lands on a row, because 25200 is on the 50-point grid.

    A table that stepped past its own peak would show a trader a maximum that is not the
    maximum, and the figure beside the chart would disagree with the rows beneath it.
    """
    table = dict(zip(straddle["table"]["forward"], straddle["table"]["pnl_at_expiry"]))

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
    rows = sorted(zip(straddle["table"]["forward"], straddle["table"]["pnl_at_expiry"]))

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

    assert body["table"]["forward"], "an empty Strategy still has a Forward axis"
    assert set(body["table"]["pnl_at_expiry"]) == {0.0}

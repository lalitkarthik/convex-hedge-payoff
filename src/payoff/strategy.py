"""Strategy aggregation: an ordered list of Legs becomes a curve and some numbers.

The rule this module exists to honour is that **every metric is computed from the list
of Legs with no branching on leg count and no knowledge of what the shape is called**
(#23). A naked call and an iron condor go down the same path, which is why adding a
Preset later (#30) adds no code here - if it ever does, something here was built wrong.

P&L at Expiry needs intrinsic value alone, so nothing in this module calls the pricing
core. That is what lets the HTTP layer ship without exposing unverified mathematics,
and it is why ADR-0001's contested spot-to-forward rule (#13) is not needed for v1.

Lot Size is applied **here, at the presentation boundary** - never stored on a Leg
(CONTEXT.md).
"""

import numpy as np

from payoff.models import Curve, Leg, Metrics

CURVE_POINTS = 400
"""#24 asks for at least 200. 400 is the width the vectorisation was measured at."""

SPOT_RANGE = 0.06
"""How far either side of Spot the curve runs. Wide enough that a four-Leg structure's
wings are visible, narrow enough that the interesting region is not a flat line."""


def intrinsic_value(spot, strike: float, *, is_call: bool):
    """What the contract is worth at Expiry, ignoring what was paid for it.

    This is **Payoff** in CONTEXT.md's sense - premium-blind. Subtracting the Entry
    Premium is what turns it into P&L, and both lines on the chart are P&L.
    """
    spot = np.asarray(spot, dtype=float)
    return np.maximum(spot - strike, 0.0) if is_call else np.maximum(strike - spot, 0.0)


def pnl_at_expiry(spot, legs: list[Leg]):
    """P&L at Expiry for the whole Strategy, across a range of Spot values.

    Signed by direction and scaled by Quantity. No branching on how many Legs there are.
    """
    total = np.zeros_like(np.asarray(spot, dtype=float))
    for leg in legs:
        value = intrinsic_value(spot, leg.strike, is_call=leg.option_type == "CE")
        total = total + leg.direction * leg.quantity * (value - leg.entry_premium)
    return total


def net_premium(legs: list[Leg]) -> float:
    """Positive is paid out (a debit); negative is received (a credit) - CONTEXT.md."""
    return float(sum(leg.direction * leg.quantity * leg.entry_premium for leg in legs))


def curve(legs: list[Leg], spot_centre: float) -> Curve:
    """The chart's line: P&L at Expiry across a range of Spot values."""
    grid = np.linspace(
        spot_centre * (1 - SPOT_RANGE), spot_centre * (1 + SPOT_RANGE), CURVE_POINTS
    )
    pnl = pnl_at_expiry(grid, legs)
    return Curve(spot=[float(s) for s in grid], pnl_at_expiry=[float(p) for p in pnl])


def _kinks(legs: list[Leg]) -> np.ndarray:
    """The Spots where the Expiry payoff changes slope, plus both tail ends.

    P&L at Expiry is piecewise linear in Spot and bends only at a strike, so these
    points describe the whole curve exactly. Spot cannot fall below zero, which is why
    the left edge is 0.0 and why only the right-hand tail can ever be Unbounded
    (CONTEXT.md).

    Working from the kinks rather than from a sampled grid is what makes the Breakevens
    exact instead of nearly right.
    """
    strikes = sorted({leg.strike for leg in legs})
    return np.array([0.0, *strikes, strikes[-1] * 2.0])


def breakevens(legs: list[Leg]) -> list[float]:
    """Every Spot at which the Expiry P&L is zero.

    A Strategy may have none, one, or several (CONTEXT.md). Between two adjacent kinks
    the curve is a straight line, so each crossing is solved rather than searched for.
    """
    points = _kinks(legs)
    pnl = pnl_at_expiry(points, legs)

    found = [float(spot) for spot, value in zip(points, pnl) if value == 0.0]
    for i in range(len(points) - 1):
        before, after = pnl[i], pnl[i + 1]
        if np.sign(before) * np.sign(after) < 0:
            left, right = points[i], points[i + 1]
            found.append(float(left - before * (right - left) / (after - before)))

    return sorted({round(value, 6) for value in found})


def _is_unbounded(legs: list[Leg], *, upside: bool) -> bool:
    """Does the far tail keep running in one direction?

    Only the right-hand tail can be Unbounded: Spot cannot fall below zero, so the
    left-hand tail always terminates (CONTEXT.md). Decided from the net signed quantity
    of calls, which governs the slope far above every strike - no leg-count branching,
    and no need to recognise the shape.
    """
    call_slope = sum(leg.direction * leg.quantity for leg in legs if leg.option_type == "CE")
    return call_slope > 0 if upside else call_slope < 0


def metrics(legs: list[Leg]) -> Metrics:
    """The four numbers under the chart, and the ratio between two of them.

    Unbounded is None, which serialises as JSON null and reads as "Unlimited". The
    extrema are read off the kinks, where a piecewise-linear curve's extrema actually
    sit: a 20,000-point scan steps about 0.6 points across this chain and misses a peak
    that sits exactly on a strike, which is how a short straddle comes to report 670.703
    where the prototype reports 670.75.
    """
    pnl = pnl_at_expiry(_kinks(legs), legs)

    max_profit = None if _is_unbounded(legs, upside=True) else float(pnl.max())
    max_loss = None if _is_unbounded(legs, upside=False) else float(pnl.min())

    # A ratio against an Unbounded gain has no meaning, and a large number in its
    # place would read as a good trade.
    reward_risk = None
    if max_profit is not None and max_loss is not None and max_loss < 0:
        reward_risk = float(max_profit / abs(max_loss))

    return Metrics(
        max_profit=max_profit,
        max_loss=max_loss,
        breakevens=breakevens(legs),
        net_premium=net_premium(legs),
        reward_risk=reward_risk,
    )

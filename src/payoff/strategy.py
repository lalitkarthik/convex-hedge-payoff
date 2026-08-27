"""Strategy aggregation: an ordered list of Legs becomes a curve and some numbers.

The rule this module exists to honour is that **every metric is computed from the list
of Legs with no branching on leg count and no knowledge of what the shape is called**
(#23). A naked call and an iron condor go down the same path, which is why adding a
Preset later (#30) adds no code here - if it ever does, something here was built wrong.

P&L at Expiry needs intrinsic value alone, so nothing in this module calls the pricing
core. That is what lets the HTTP layer ship without exposing unverified mathematics,
and it is why ADR-0001's contested spot-to-forward rule (#13) is not needed here.

**Every x in this module is a Forward, end to end (#72).** The stored corners sit on a
Forward domain, the window the chart shows is centred on the Forward, and the array that
goes out on the wire is called `Curve.forward` because that is what it holds. There is no
`S -> F` anywhere between those three, which is the property CONTEXT.md now states for
the chart and ADR-0001 already stated for the core.

**The Expiry line is read, not computed (#70).** A Payoff is flat, then straight, and
bends exactly once, so three corner points describe it exactly and linear interpolation
between them reconstructs it without error. `scripts/build_runtime.py` writes those
corners once for the whole dataset and everything below reads them - the chart, the
table, the Breakevens and the extrema all come off the one stored shape, which is what
makes it impossible for the number beside the chart to disagree with the picture.

**The corners of every Leg sit on one shared, absolute Forward domain**, whose bounds are
published in the manifest and read from there rather than named here. Legs are summed by
adding their values at the same Forward; a domain centred on each Leg's own strike sums
points that are not the same point, and the sum is wrong without ever looking wrong. That
failure once reported a two-Leg delta of -157 where the true figure was +742.

**One Expiry per Strategy (#71).** Every line below is the P&L *at Expiry*, so a Strategy
spanning two series has no single line to be: at the near one the far Leg has not expired.
`sole_expiry` is where that is refused, and it is refused rather than approximated because
the approximation looks exactly like an answer.

Lot Size is applied **here, at the presentation boundary** - never stored on a Leg
(CONTEXT.md).
"""

from collections.abc import Sequence
from datetime import date
from functools import lru_cache

import numpy as np

from payoff import catalog, pricing, store
from payoff.models import Curve, Leg, LegGreeks, LegRequest, Metrics

CURVE_POINTS = 400
"""#24 asks for at least 200. 400 is the width the vectorisation was measured at."""

FORWARD_RANGE = 0.06
"""How far either side of the **Forward** the chart's window runs - a framing choice, not
the domain the Payoff is defined on. The domain is the whole dataset's and comes from the
manifest; this only decides how much of it a trader is shown. Wide enough that a four-Leg
structure's wings are visible, narrow enough that the interesting region is not a flat
line.

**Either side of the Forward and not of Spot** (#72). The window was centred on Spot,
which is a Spot-to-Forward conversion with the basis assumed to be zero - and it is
+118.87 at the anchor, so the window sat 118.87 points to the left of the axis it was
drawn on. Nothing looked wrong, because a window is symmetric about whatever it is
handed."""


class MixedExpiry(ValueError):
    """A Strategy whose Legs do not all expire on the same day (#71).

    **Refused rather than drawn.** Every line this module produces is the P&L *at Expiry*,
    and a Strategy spanning two series has no single one: at the near Expiry the far Leg
    has not expired, so it is worth a price rather than a Payoff, and pricing it needs the
    Target Date line that #64 puts out of scope for this whole epic.

    The failure that makes this worth an exception is that nothing downstream would catch
    it. Summing the two Legs' Payoffs produces a curve with the right number of kinks in
    plausible places; a trader would read a Breakeven off it and size a position against
    it. Refusing is the only outcome that is visibly wrong when it is wrong.

    A `ValueError` rather than a `LookupError`: both series may be perfectly well stored,
    so nothing is missing. It is the combination that cannot be answered, which is what
    422 means and what `api.py` turns this into.
    """

    def __init__(self, spanned: Sequence[date]) -> None:
        self.spanned = tuple(spanned)
        named = ", ".join(catalog.label(one) for one in self.spanned)
        super().__init__(
            f"a Strategy's Legs must all share one Expiry, and these span {len(self.spanned)}: "
            f"{named}. At the near Expiry the far Leg has not expired - it has a price, not "
            "a Payoff - so there is no single Expiry line to draw for this Strategy. "
            "Analyse one series at a time."
        )


def sole_expiry(legs: Sequence[LegRequest | Leg]) -> date | None:
    """The one Expiry every Leg names, or `MixedExpiry` if they name more than one.

    **Checked before anything is looked up**, which is what makes the error the one a
    caller needs. A Strategy pairing this Expiry with one the store never held would
    otherwise fail as `24FEB26 did not trade on 2026-01-27` - true, and about the wrong
    subject, because the Strategy would still be unanswerable on a day that traded both.

    The set is built from **parsed** Expiries rather than from the labels, so a link
    holding two spellings of one series is one Expiry rather than two, and text that is
    not an Expiry at all says so here (`catalog.UnreadableExpiry`, a 422) instead of
    filtering the store to nothing several frames down.

    `None` for a Strategy with no Legs - the page opens in that state and it is a
    reachable URL, so it is not an error. It means "no series was named", and every reader
    below treats that as it always has: the day's own, whatever the day traded.

    Nothing here is shaped by the dataset holding exactly one Expiry today. A set of one
    is not a special case of this function; it is the ordinary answer.
    """
    spanned = sorted({catalog.parse_label(leg.expiry) for leg in legs})
    if len(spanned) > 1:
        raise MixedExpiry(spanned)
    return spanned[0] if spanned else None


class PayoffNotStored(LookupError):
    """A Leg whose contract has no corner points in the store.

    Raised rather than fallen back on. The fallback - recomputing `max(F - K, 0)` here
    for the one contract that is missing - would draw a line that agrees with the stored
    ones everywhere and would hide the fact that the artifact is stale, which is the one
    thing worth knowing.
    """

    def __init__(self, strike: float, option_type: str) -> None:
        super().__init__(
            f"{strike:.0f} {option_type} has no stored Payoff. Run "
            "`python scripts/build_runtime.py` to write the corner points."
        )


def intrinsic_value(forward, strike: float, *, is_call: bool):
    """What the contract is worth at Expiry, ignoring what was paid for it.

    This is **Payoff** in CONTEXT.md's sense - premium-blind. Subtracting the Entry
    Premium is what turns it into P&L, and both lines on the chart are P&L.

    Since #70 the serving path does not call this: it reads the corner points instead.
    What calls it is the **build** that writes them, which is deliberate - one definition
    of a Payoff, evaluated once at three points per contract rather than at four hundred
    points per request.
    """
    forward = np.asarray(forward, dtype=float)
    return np.maximum(forward - strike, 0.0) if is_call else np.maximum(strike - forward, 0.0)


@lru_cache(maxsize=1)
def corner_points() -> dict[tuple[float, str], tuple[np.ndarray, np.ndarray]]:
    """Every contract's Payoff, as the three points that describe it exactly.

    Cached because the artifact is a few hundred rows and the store is immutable for the
    life of the process. Read whole rather than filtered per request: filtering a file
    this small costs more than reading it.
    """
    rows = (
        store.scan(store.runtime_root(), store.PAYOFF)
        .select("strike", "option_type", "corner", "forward", "payoff")
        .sort("strike", "option_type", "corner")
        .collect()
    )

    corners: dict[tuple[float, str], tuple[list[float], list[float]]] = {}
    for strike, option_type, _, forward, payoff in rows.rows():
        xs, ys = corners.setdefault((float(strike), str(option_type)), ([], []))
        xs.append(float(forward))
        ys.append(float(payoff))

    return {key: (np.array(xs), np.array(ys)) for key, (xs, ys) in corners.items()}


@lru_cache(maxsize=1)
def forward_domain() -> tuple[float, float]:
    """The two bounds every stored corner sits on, read from the manifest.

    **From the manifest and not from a constant here.** The writer laid the outer corners
    down at these two Forwards; a reader that assumed a different pair would interpolate
    over a segment that was never stored, and the error would be a smooth, plausible line
    rather than an exception.
    """
    bounds = (
        store.scan(store.runtime_root(), store.MANIFEST)
        .select("forward_min", "forward_max")
        .unique()
        .collect()
    )
    if bounds.height != 1:
        raise ValueError(
            f"the manifest publishes {bounds.height} Forward domains; a shared domain is one"
        )
    return float(bounds["forward_min"][0]), float(bounds["forward_max"][0])


def leg_payoff(forward, leg: Leg):
    """One Leg's Payoff at any Forward, reconstructed from its stored corners.

    `np.interp` is **exact** here rather than approximate: the function genuinely is a
    straight line between the corners, so interpolating it recovers the same number the
    formula would have. That is the property a sampled grid does not have - it cuts the
    corner unless a sample lands precisely on the strike.
    """
    key = (leg.strike, leg.option_type)
    stored = corner_points().get(key)
    if stored is None:
        raise PayoffNotStored(*key)
    return np.interp(np.asarray(forward, dtype=float), *stored)


def pnl_at_expiry(forward, legs: list[Leg]):
    """P&L at Expiry for the whole Strategy, across a range of Forward values.

    Signed by direction and scaled by Quantity. No branching on how many Legs there are.
    Every Leg is evaluated at the Forwards it was handed, which are the same Forwards
    every other Leg is handed - that is what makes the sum a sum.
    """
    total = np.zeros_like(np.asarray(forward, dtype=float))
    for leg in legs:
        value = leg_payoff(forward, leg)
        total = total + leg.direction * leg.quantity * (value - leg.entry_premium)
    return total


def net_premium(legs: list[Leg]) -> float:
    """Positive is paid out (a debit); negative is received (a credit) - CONTEXT.md."""
    return float(sum(leg.direction * leg.quantity * leg.entry_premium for leg in legs))


def curve(legs: list[Leg], forward_centre: float) -> Curve:
    """The chart's line: P&L at Expiry across the window a trader is shown.

    Four hundred evenly spaced points **plus every corner that falls inside the window**
    (#70). The even spacing is what makes the line smooth to draw; the corners are what
    make it right, and they are the points an evenly spaced grid is guaranteed to miss -
    7.55 points apart on this chain, so a strike lands between two samples and the peak
    the chart draws is a chord across the vertex rather than the vertex.

    That was visible before this ticket: a short straddle peaked at 668.59 on the chart
    while the figure printed beside it said 670.75. Both were honest; they were samples
    of one curve on two grids. Neither is a thing to have to explain to a trader.

    The window is clipped to the stored domain, because there is nothing to interpolate
    outside it and `np.interp` would flatten the line rather than say so.

    **Centred on the Forward** (#72), which is what the axis is measured in. It was
    centred on Spot, and the two are 118.87 apart at the anchor.
    """
    low, high = forward_domain()
    left = max(forward_centre * (1 - FORWARD_RANGE), low)
    right = min(forward_centre * (1 + FORWARD_RANGE), high)

    grid = np.linspace(left, right, CURVE_POINTS)
    corners = _corners(legs)
    points = np.unique(np.concatenate([grid, corners[(corners > left) & (corners < right)]]))

    pnl = pnl_at_expiry(points, legs)
    return Curve(forward=[float(f) for f in points], pnl_at_expiry=[float(p) for p in pnl])


TABLE_STEP = 50.0
"""The strike spacing on this chain (#29).

Rows land on strikes a trader could actually have traded, which is what makes the table
readable against the Chain beside it. An interval picked for round numbers, or by
dividing the range into N, would put rows between strikes.
"""


def payoff_table(legs: list[Leg], forward_centre: float, step: float = TABLE_STEP) -> Curve:
    """The same P&L at Expiry as `curve`, sampled on the grid a trader reads.

    **One computation, two presentations.** This is not a second calculation of the
    chart - it is `pnl_at_expiry` again, on a coarser and rounder grid, which is why the
    two agree exactly wherever they share a Forward. Publishing it beside the curve rather
    than from an endpoint of its own is what keeps that true (#23, #29).

    The grid is snapped to multiples of `step` rather than started at the range edge, so
    the rows are 25,150 and 25,200 rather than 25,144.235 and 25,194.235 - and so the
    strike itself is a row, which matters because that is where a straddle peaks.
    """
    low = np.ceil(forward_centre * (1 - FORWARD_RANGE) / step) * step
    high = np.floor(forward_centre * (1 + FORWARD_RANGE) / step) * step
    grid = np.arange(low, high + step / 2, step)
    pnl = pnl_at_expiry(grid, legs)
    return Curve(forward=[float(f) for f in grid], pnl_at_expiry=[float(p) for p in pnl])


def _corners(legs: list[Leg]) -> np.ndarray:
    """The Forwards where the Expiry P&L changes slope, plus both ends of the domain.

    P&L at Expiry is piecewise linear in the Forward and bends only at a strike, so these
    points describe the whole curve exactly - and because every Leg's stored corners sit
    on the same domain, they describe it for the Strategy and not merely for one Leg.

    **The two ends come from the manifest** (#70) and are not written here. They used to
    be: `0.0` and twice the Strategy's own highest strike. The lower one was right - the
    Forward cannot fall below zero, which is why only the right-hand tail can ever be
    Unbounded (CONTEXT.md) - and the upper one was a per-Strategy number masquerading as
    a shared one. Reading both from the manifest is what stops the reader's idea of the
    domain and the writer's from drifting apart.

    A Strategy with **no Legs** has no strikes: its P&L is flat zero everywhere, and the
    two ends of the domain are returned on their own. Some points are returned rather
    than none, because the callers take a max and a min over this and an empty array has
    neither. No Legs is not an error state - it is what the page opens in, and it is a
    reachable URL now that the analysis has an address of its own.
    """
    low, high = forward_domain()
    return np.array([low, *sorted({leg.strike for leg in legs}), high])


def breakevens(legs: list[Leg]) -> list[float]:
    """Every Forward at which the Expiry P&L is zero.

    A Strategy may have none, one, or several (CONTEXT.md). Between two adjacent corners
    the curve is a straight line, so each crossing is solved rather than searched for -
    and it is solved on the same corner points the chart is drawn through, so a Breakeven
    is a level the line visibly crosses rather than one it nearly does.

    **No Legs means no Breakevens**, and specifically not "a Breakeven at zero". A flat
    line at zero is zero at every Forward, so the crossing test would find both ends of
    the domain and publish them - Forwards at which NIFTY does not trade, presented as
    levels the trader breaks even at.
    """
    if not legs:
        return []

    points = _corners(legs)
    pnl = pnl_at_expiry(points, legs)

    found = [float(forward) for forward, value in zip(points, pnl) if value == 0.0]
    for i in range(len(points) - 1):
        before, after = pnl[i], pnl[i + 1]
        if np.sign(before) * np.sign(after) < 0:
            left, right = points[i], points[i + 1]
            found.append(float(left - before * (right - left) / (after - before)))

    return sorted({round(value, 6) for value in found})


def _is_unbounded(legs: list[Leg], *, upside: bool) -> bool:
    """Does the far tail keep running in one direction?

    Only the right-hand tail can be Unbounded: the Forward cannot fall below zero, so the
    left-hand tail always terminates (CONTEXT.md). Decided from the net signed quantity
    of calls, which governs the slope far above every strike - no leg-count branching,
    and no need to recognise the shape.
    """
    call_slope = sum(leg.direction * leg.quantity for leg in legs if leg.option_type == "CE")
    return call_slope > 0 if upside else call_slope < 0


def metrics(legs: list[Leg]) -> Metrics:
    """The four numbers under the chart, and the ratio between two of them.

    Unbounded is None, which serialises as JSON null and reads as "Unlimited". The
    extrema are read off the corner points, where a piecewise-linear curve's extrema
    actually sit: a 20,000-point scan steps about 0.6 points across this chain and misses
    a peak that sits exactly on a strike, which is how a short straddle comes to report
    670.703 where the prototype reports 670.75.

    Since #70 those corner points are the ones the chart is drawn through, so the figure
    printed beside the chart and the vertex the chart draws are the same number rather
    than two honest samples of one curve (#64 story 16).
    """
    pnl = pnl_at_expiry(_corners(legs), legs)

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


def leg_greeks(legs: list[Leg], forward: float, discount: float, T: float) -> list[LegGreeks]:
    """Each Leg's exposures, signed by its Direction and scaled by its Quantity (#27).

    Priced on the **forward**, never on a spot: no `S -> F` conversion appears here,
    which is what lets #13 stay open. Everything not named as the perturbation is held -
    in particular each Leg keeps its own strike's volatility, so a spread's two Legs are
    priced at the two volatilities the smile actually quotes rather than at one average.

    Per contract. The Lot Size multiplier is #29's and lives above this line.
    """
    rows = []
    for leg in legs:
        greeks = pricing.black76_greeks(
            forward, leg.strike, T, leg.iv, discount, is_call=leg.option_type == "CE"
        )
        scale = leg.direction * leg.quantity
        rows.append(
            LegGreeks(**{name: scale * float(greeks[name]) for name in LegGreeks.model_fields})
        )
    return rows


def total_greeks(rows: list[LegGreeks]) -> LegGreeks | None:
    """`G = sum_i d_i q_i g_i` - the signing already happened, so this only adds up.

    No branching on Leg count and none on Strategy name (#23 story 45): a Strategy is an
    ordered list of Legs, so its exposure is the sum of theirs and adding a Preset adds
    no code here.
    """
    if not rows:
        return None
    return LegGreeks(
        **{
            name: sum(getattr(row, name) for row in rows)
            for name in LegGreeks.model_fields
        }
    )

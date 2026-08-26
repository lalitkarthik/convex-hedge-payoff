"""The Forward and the Discount Factor, recovered from the option prices (#51).

Put-call parity is an identity for European options on one strike and one expiry. No
model, no volatility, no distributional assumption:

    C(K) - P(K) = D (F_hat - K)

As a function of K that is a straight line, so one ordinary least squares fit over the
strikes quoting **both** sides recovers both unknowns at once: the slope is -D and the
intercept is D F_hat.

**Not every minute supports a line.** On 60 of the sample day's 376 the fit is either
unavailable or untrustworthy, and this module descends a three-tier ladder rather than
refusing the minute - a refused minute takes the chain, the volatilities and every Greek
down with it. What it must never do is disguise which tier answered, so every result
names its own method.

    1. parity_fit             the gated regression                     316 minutes
    2. single_strike_parity   parity at one strike, r assumed at 6.5%   50 minutes
    3. spot                   F = S, nothing better is available        10 minutes

Tier 2 assumes a rate only to build a discount factor. It does **not** carry that rate
through to the forward as F = S/D: measured against the session, that rule misses by a
median of 54.63 points, more than a full 50-point strike interval, which is the failure
ADR-0001 exists to catch. The forward always comes out of traded prices.

Tier 3 is entered on one rule with no constant in it: parity needs a quote on both sides
of the strike nearest spot, and where that strike is unpaired there is nothing to invert.

Like `pricing.py`, this module takes numbers and returns numbers. It never sees a chain;
slicing one belongs a layer up (ADR-0001).
"""

from dataclasses import dataclass

import numpy as np

FALLBACK_RATE = 0.065
"""The rate assumed when the regression cannot be trusted. It reaches the discount factor
and stops there - it is never an input to the forward, and never leaves this module."""

MIN_PAIRS = 5
"""Fewer paired strikes than this and a straight line through them means nothing."""

MAX_RATE = 0.30
"""An implied rate at or above this says the slope is wrong, not that money is expensive."""


@dataclass(frozen=True)
class ForwardFit:
    """One moment's forward and discount, and an honest account of where they came from."""

    forward: float
    discount: float
    T: float
    """Years to Expiry on the trading-day clock, carried rather than recomputed: the fit
    already needed it, and the Greeks need the same one (#53)."""


    method: str
    """`parity_fit`, `single_strike_parity` or `spot`. A forward that was assumed must not
    be mistakable for one that was measured: on the 10 `spot` minutes the basis is forced
    to zero when it is really around 120 points, and #52's volatilities and #53's Greeks
    both price off this number."""

    pairs: int
    """How many strikes quoted both sides. The regression's sample size where there was
    one, and the reason there was not where there was not."""


def fit_forward(strikes, calls, puts, quoted_strikes, *, T, spot) -> ForwardFit:
    """Recover the forward and the discount at one moment.

    `strikes`, `calls` and `puts` are aligned arrays over the strikes quoting **both**
    sides. `quoted_strikes` is every strike quoted at that moment, either side, which
    tier 2 needs to ask whether the strike nearest spot is one of the paired ones.

    Returns a `ForwardFit` for any input. There is no failure mode and no NaN; where the
    evidence runs out the method says so.
    """
    strikes = np.asarray(strikes, dtype=float)
    calls = np.asarray(calls, dtype=float)
    puts = np.asarray(puts, dtype=float)
    quoted = np.asarray(quoted_strikes, dtype=float)
    pairs = int(strikes.size)

    if pairs >= MIN_PAIRS and T > 0.0:
        slope, intercept = np.polyfit(strikes, calls - puts, 1)
        discount = float(-slope)

        # Guard the sign before taking the log rather than letting a NaN fail the
        # comparison. A discount above 1 is being paid to wait, which the slope allows
        # and the market does not.
        if 0.0 < discount <= 1.0 and 0.0 < -np.log(discount) / T < MAX_RATE:
            return ForwardFit(float(intercept / discount), discount, T, "parity_fit", pairs)

    discount = float(np.exp(-FALLBACK_RATE * T))

    if quoted.size:
        nearest = float(quoted[np.abs(quoted - spot).argmin()])
        paired_here = np.flatnonzero(strikes == nearest)
        if paired_here.size:
            at = int(paired_here[0])
            forward = nearest + (calls[at] - puts[at]) / discount
            return ForwardFit(float(forward), discount, T, "single_strike_parity", pairs)

    return ForwardFit(float(spot), discount, T, "spot", pairs)

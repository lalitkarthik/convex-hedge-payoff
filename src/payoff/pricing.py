"""The pricing core: Black-76 on a Forward, and the Oracle's Greek conventions.

**Per ADR-0001 this takes a Forward and a Discount Factor, never a Spot and a rate.**
Anyone expecting a spot argument will be surprised, which is what that ADR exists to
explain: the implied continuous rate runs from 0.9% to 28.4% across the dataset and
diverges as T approaches zero, and on 28.7% of minutes a Forward cannot be fitted at
all. Hiding that reconstruction inside a pricing function would make its output depend
on a conversion rule nobody chose deliberately. The conversion lives above the seam.

Time is the **trading-day clock**: one session is exactly 1.0 and a year is 252 of
them, so nothing decays overnight or over a weekend. Volatility crosses this interface
as a decimal, never a percentage.
"""

import numpy as np
from scipy.stats import norm

TRADING_DAYS_PER_YEAR = 252
"""One session is exactly 1.0 day. Calendar time does not appear in this module."""


def _require_positive_volatility(vol: np.ndarray) -> None:
    """ADR-0001 bans NaN in the core: raise instead.

    A zero volatility divides by zero and a negative one is worse - it returns a number
    that looks like a price (-86.41 for a call worth 299.10), survives a chart and
    survives review. Raising is the only outcome a caller cannot ignore.
    """
    if not np.all(vol > 0.0):
        raise ValueError("volatility must be positive - it is a decimal, never a percentage")


def black76_price(forward, strike, T, vol, discount, *, is_call: bool):
    """The Black-76 value of a European option on a Forward.

    At T = 0 the option is worth its discounted intrinsic value. That is the Expiry
    line the payoff chart draws, not an error case - a core that raised here would push
    the green line onto a path nothing verifies.
    """
    forward = np.asarray(forward, dtype=float)
    strike = np.asarray(strike, dtype=float)
    vol = np.asarray(vol, dtype=float)
    T = np.asarray(T, dtype=float)
    _require_positive_volatility(vol)

    intrinsic = (
        np.maximum(forward - strike, 0.0) if is_call else np.maximum(strike - forward, 0.0)
    )

    # T is an array in practice - the sample's dte_days varies within a single minute -
    # so the Expiry case is selected elementwise rather than branched on. The live
    # branch is evaluated at a substituted T wherever it would divide by zero, and
    # thrown away there; that keeps one vectorised path instead of two.
    expired = T <= 0.0
    T_live = np.where(expired, 1.0, T)

    v = vol * np.sqrt(T_live)
    d1 = (np.log(forward / strike) + 0.5 * vol**2 * T_live) / v
    d2 = d1 - v

    if is_call:
        live = discount * (forward * norm.cdf(d1) - strike * norm.cdf(d2))
    else:
        live = discount * (strike * norm.cdf(-d2) - forward * norm.cdf(-d1))

    return np.where(expired, discount * intrinsic, live)


def black76_greeks(forward, strike, T, vol, discount, *, is_call: bool) -> dict:
    """Delta, gamma, vega, theta and rho. Several conventions are not textbook.

    They are not converted for readability - a confusing convention is a labelling
    problem, not a maths problem:

    | **delta, gamma** | **undiscounted** - see below                          |
    | vega             | per volatility point (a 1% move, so divided by 100)   |
    | rho              | per one percent                                       |
    | **theta**        | **a one-trading-day repricing, not the analytic form** |

    **Delta and gamma are undiscounted, which is the Oracle's convention.** The Black-76
    price is `D[F N(d1) - K N(d2)]`, so a strict derivative of it inherits the D and
    delta would be `D N(d1)`, bounded by `[0, D]`. #53 took that reading and this engine
    reported it; it is reverted here because the Oracle - the shipped platform Greeks
    this project grades itself against - reports `N(d1)`, and a convention the desk does
    not use is a convention that has to be undone at every boundary.

    Delta is therefore bounded by `[0, 1]` for a call and `[-1, 0]` for a put, and
    `test_oracle.py` now compares against the file directly with no rescaling on either
    side. The two agree to 2.2e-16.

    **Vega and rho keep their D**, because the Oracle discounts those. That asymmetry is
    the Oracle's, not ours.

    The theta convention is the expensive trap. Against the Oracle the repricing
    definition matches to 1.1e-11, while an analytic theta divided down to one session
    is out by about 5e-01 (#26 records 4.1e-01 for its variant) - large enough to see
    and small enough to look like a bug in something else. Theta here is
    what the position is worth after one session has passed and nothing else has moved,
    which is also the number a trader reads it as.
    """
    forward = np.asarray(forward, dtype=float)
    strike = np.asarray(strike, dtype=float)
    vol = np.asarray(vol, dtype=float)
    T = np.asarray(T, dtype=float)
    discount = np.asarray(discount, dtype=float)
    _require_positive_volatility(vol)
    if not np.all(T > 0.0):
        # The price at Expiry is well defined - it is the chart's green line. The
        # exposures are not: gamma divides by a time-scaling that is zero, and theta is
        # the change over a session that no longer exists.
        raise ValueError("the Greeks are undefined at Expiry - price there instead")

    v = vol * np.sqrt(T)
    d1 = (np.log(forward / strike) + 0.5 * vol**2 * T) / v
    d2 = d1 - v

    price = black76_price(forward, strike, T, vol, discount, is_call=is_call)

    # The rate implied by the Discount Factor, used only to re-discount one day nearer
    # Expiry. It is never an input and never leaves this function - ADR-0001 keeps it
    # out of the interface because it runs from 0.9% to 28.4% across the dataset.
    rate = -np.log(discount) / T
    T_next = np.maximum(T - 1.0 / TRADING_DAYS_PER_YEAR, 0.0)
    discount_next = np.exp(-rate * T_next)
    repriced = black76_price(forward, strike, T_next, vol, discount_next, is_call=is_call)

    return {
        "price": price,
        # Undiscounted, matching the Oracle. See the convention table above: vega and
        # rho below DO carry the D, because the Oracle discounts those two.
        "delta": norm.cdf(d1) if is_call else norm.cdf(d1) - 1.0,
        "gamma": norm.pdf(d1) / (forward * v),
        "vega": discount * forward * norm.pdf(d1) * np.sqrt(T) / 100,
        "theta": repriced - price,
        "rho": (
            discount * strike * T * norm.cdf(d2) if is_call
            else -discount * strike * T * norm.cdf(-d2)
        ) / 100,
    }


VOL_SEARCH_BRACKET = (1e-6, 5.0)
"""Where the solver is allowed to go. The sample's solved volatilities run 0.098 to
0.250, so 500% is far outside anything this market quotes - wide enough that hitting the
edge means the price is not attainable at any volatility, not that the search was too
narrow."""

VOL_SEED = 0.20
"""The flat seed every row starts from, and the weakest constant in this module.

Section 4 measures it: Brenner-Subrahmanyam, the textbook seed, converges on 22 of the
anchor's 46 legs, and a flat 0.20 on all 46 in a median of 4 iterations. But the safety
is **one-sided**. Sweeping the seed across the day's 18,994 invertible rows, everything
from 0.15 upwards converges and 2.00 costs only three extra sweeps, while 0.10 fails 958
rows and 0.05 fails 9,479. The cliff is between 0.10 and 0.15 - 0.05 below this seed -
and the day's own volatilities reach down to 0.098. A quieter day sits under it.

It is a constant fitted to one expiry in one market and it will have to change. The
replacement is a bisection fallback or a moneyness-aware seed, not a different number."""

VOL_TOLERANCE = 1e-8
"""Convergence, measured on the **residual** rather than on the volatility. It is the
price that is driven to zero, and a hundredth of a paisa means a different thing at each
strike; a tolerance in volatility units would be tighter on the wings than at the money
without anyone choosing that."""

MAX_SWEEPS = 50
"""Newton's ceiling. Five is enough for every row of the sample; fifty is a runaway
guard, not a working budget. Callers that want the count to *mean* something - the test
that catches the vega divided by 100 - pass a tighter one."""

VEGA_FLOOR = 1e-12
"""Below this the tangent is flat and the step diverges. As volatility falls the price
collapses onto intrinsic and vega decays super-exponentially: at a Brenner-Subrahmanyam
seed of 0.0116 on the 23,500 put, vega is 3.8e-189 - 191 orders of magnitude below its
value at the answer. No step size recovers from that, so the sweep stops instead."""


def implied_vol(price, forward, strike, T, discount, *, is_call: bool, max_sweeps=MAX_SWEEPS):
    """The volatility that reproduces `price` under this module's own Black-76.

    Newton-Raphson, every row at once, seeded flat. The derivative is a Greek this
    module already knows - vega - but it must be the **raw** one:

        f(s)  = Black76(F, K, T, s, D) - price
        f'(s) = D F phi(d1) sqrt(T)

    `black76_greeks` returns that divided by 100, because the Oracle quotes vega per
    volatility *point*. Feeding the Oracle's form to Newton makes every step a hundred
    times too small: the solver still converges, just several hundred iterations later,
    so it reads as sluggishness rather than as the bug it is. The formula is written out
    here rather than reused for exactly that reason.

    The tolerance is in **price** units, not volatility units - it is the residual that
    is driven to zero, and a hundredth of a paisa of price is a different quantity at
    each strike.

    Price is monotonically increasing in volatility, so a price the bracket cannot reach
    is a price no volatility reproduces. That raises rather than returning the edge of
    the search: silently handing back 500% would put a plausible curve on the screen
    (ADR-0001).
    """
    price = np.asarray(price, dtype=float)
    forward = np.asarray(forward, dtype=float)
    strike = np.asarray(strike, dtype=float)
    T = np.asarray(T, dtype=float)
    discount = np.asarray(discount, dtype=float)

    low, high = VOL_SEARCH_BRACKET
    vol = np.full(np.broadcast(price, forward, strike, T, discount).shape, VOL_SEED)

    for _ in range(max_sweeps):
        residual = black76_price(forward, strike, T, vol, discount, is_call=is_call) - price
        if np.all(np.abs(residual) < VOL_TOLERANCE):
            return vol

        d1 = (np.log(forward / strike) + 0.5 * vol**2 * T) / (vol * np.sqrt(T))
        vega = discount * forward * norm.pdf(d1) * np.sqrt(T)

        # A collapsed vega stops that row rather than launching it: the step is the
        # residual over a number on its way to zero. The row then fails the convergence
        # check below, which is the outcome that gets reported.
        collapsed = vega < VEGA_FLOOR
        step = np.where(collapsed, 0.0, residual / np.where(collapsed, 1.0, vega))
        moved = np.clip(vol - step, low, high)
        if np.array_equal(moved, vol):
            break
        vol = moved

    residual = black76_price(forward, strike, T, vol, discount, is_call=is_call) - price
    unsolved = int(np.count_nonzero(np.abs(residual) >= VOL_TOLERANCE))
    if unsolved:
        raise ValueError(f"no volatility reproduces the price on {unsolved} of {vol.size} rows")
    return vol

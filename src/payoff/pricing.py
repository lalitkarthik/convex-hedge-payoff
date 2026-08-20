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
    """Delta, gamma, vega, theta and rho **in the Oracle's conventions**.

    Several of them are not textbook, and they are not converted for readability - a
    confusing convention is a labelling problem, not a maths problem:

    | delta, gamma | undiscounted                                          |
    | vega         | per volatility point (a 1% move, so divided by 100)   |
    | rho          | per one percent                                       |
    | **theta**    | **a one-trading-day repricing, not the analytic form** |

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
"""Where the solver looks. The sample's volatilities run 0.098 to 0.250, so 500% is
far outside anything this market quotes - wide enough that a bracket failure means the
price is not attainable at any volatility, not that the search was too narrow."""

BISECTION_STEPS = 100
"""Halving a bracket 100 times exhausts double precision many times over. It is a fixed
count rather than a convergence check so the work is the same on every row, which is
what keeps the solve vectorised."""


def implied_vol(price, forward, strike, T, discount, *, is_call: bool):
    """The volatility that reproduces `price` under this module's own Black-76.

    Solved by bisection over every row at once. Newton's method would need fewer steps
    per row but branches per row on convergence, which is exactly the loop the
    vectorisation exists to avoid; 100 halvings cost 100 vectorised prices regardless
    of how many rows there are.

    Price is monotonically increasing in volatility, so a bracket that does not contain
    the price contains no solution at all - that raises rather than returning the edge
    of the search, because silently returning 500% volatility would put a plausible
    curve on the screen (ADR-0001).
    """
    price = np.asarray(price, dtype=float)
    low = np.full(price.shape, VOL_SEARCH_BRACKET[0], dtype=float)
    high = np.full(price.shape, VOL_SEARCH_BRACKET[1], dtype=float)

    def priced_at(vol):
        return black76_price(forward, strike, T, vol, discount, is_call=is_call)

    if np.any(price < priced_at(low)) or np.any(price > priced_at(high)):
        raise ValueError("no volatility in the search bracket reproduces this price")

    for _ in range(BISECTION_STEPS):
        middle = 0.5 * (low + high)
        too_low = priced_at(middle) < price
        low = np.where(too_low, middle, low)
        high = np.where(too_low, high, middle)

    return 0.5 * (low + high)

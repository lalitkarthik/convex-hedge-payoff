"""Deriving a day - everything the store is built from, and nothing that serves it.

The engine derives every number it publishes: the Forward and the Discount Factor by
put-call parity (#51), the volatility by Newton (#52), the Greeks from Black-76 (#53).
On the sample day the first two cost **1.4 s**, and until #66 every process paid that at
start-up, for a day that had already happened and could not change.

So the two halves are separate modules. **This one solves.** It reads a seed built by
`seed.py` out of `Data/options.parquet` and `Data/index.parquet`, and it is imported by
`scripts/build_runtime.py` and by `tests/test_implied_vol.py` and by nothing else.
**`chain.py` reads**, from the partitioned store the build writes. Nothing in the serving
path imports this module, which is what turns the 1.4 s from a boot cost into a build
cost.

**Every function here takes a date.** Until #67 there was one - the anchor - because
there was one committed seed and no way to make another. The anchor survives as a
default so that the notebook and `tests/test_implied_vol.py` still read what they always
read, and so that a figure published in `docs/calculations.md` still has a no-argument
spelling that produces it.

The Oracle direction is unchanged and is now structural rather than enforced:
`Data/greeks.parquet` is **never opened** by anything under `src/` or `scripts/`, so
there is no column to drop and no accident to guard against. `tests/test_seed.py` asserts
that, because it is the sort of property that decays the moment somebody needs one
convenient column. CONTEXT.md:138.
"""

from datetime import date
from functools import lru_cache

import numpy as np
import pandas as pd

from payoff import forward as forward_maths
from payoff import pricing, seed
from payoff.chain import StrikeNotQuoted
from payoff.pricing import TRADING_DAYS_PER_YEAR, implied_vol

ANCHOR = date(2026, 1, 27)
"""The date every published figure was measured at, and the default of every function
below. Not a limit any more - #67 derives all twenty-four - but still the day
`docs/calculations.md` quotes and the day a regression is easiest to read."""


@lru_cache(maxsize=4)
def load_chain(day: date = ANCHOR) -> pd.DataFrame:
    """One day's quoted bars, joined out of the raw files by `seed.seed`.

    Cached small rather than unbounded: a full build walks the dates once, in order, and
    a day's frame is up to 48,000 rows. Holding four is enough to keep the second read of
    a day free without holding the dataset.
    """
    return seed.seed(day).sort_values("ts").reset_index(drop=True)


def paired_quotes(rows: pd.DataFrame) -> pd.DataFrame:
    """One row per strike quoting **both** sides, with the two prices beside each other.

    Parity is an identity about a call and its put at one strike, so a strike quoting
    only one side has nothing to say and is dropped rather than half-used.

    An intersection rather than a `pivot_table`, which produced the same frame on all
    376 minutes and cost 4.7 ms of pandas overhead each time to reshape 58 rows. #52
    calls this for every minute of the day at once, which turned that into 1.8 seconds.
    """
    calls = rows[rows.option_type == "CE"]
    puts = rows[rows.option_type == "PE"]
    shared, call_at, put_at = np.intersect1d(
        calls.strike.to_numpy(float), puts.strike.to_numpy(float), return_indices=True
    )
    return pd.DataFrame(
        {"CE": calls["last"].to_numpy(float)[call_at], "PE": puts["last"].to_numpy(float)[put_at]},
        index=pd.Index(shared, name="strike"),
    )


@lru_cache(maxsize=4)
def fits(day: date = ANCHOR) -> dict[pd.Timestamp, forward_maths.ForwardFit]:
    """The Forward and Discount Factor every minute of the day implies (#51).

    Fitted **strictly**, minute by minute: the as-of view mixes quote ages up to 153
    minutes apart and the regression's slope *is* the Discount Factor, so a stale print
    would land in it directly. Each result names the tier that produced it, because on 60
    of the anchor's 376 minutes the regression cannot be trusted and the answer is
    assumed rather than measured.

    One `groupby` pass rather than a mask of the whole frame per minute. The mask was
    affordable at one date and 23,581 rows; across twenty-four dates and 568,736 it is
    the difference between a build and a coffee break.

    This is the expensive half of the 1.4 s, and it runs in the build.
    `chain.forward_at` reads the answer back off the row the build wrote.
    """
    chain = load_chain(day)
    return {
        stamp: forward_maths.fit_forward(
            strikes=(paired := paired_quotes(rows)).index.to_numpy(float),
            calls=paired.CE.to_numpy(float),
            puts=paired.PE.to_numpy(float),
            quoted_strikes=rows.strike.unique(),
            T=float(rows.dte_days.iloc[0]) / TRADING_DAYS_PER_YEAR,
            spot=float(rows.spot.iloc[0]),
        )
        for stamp, rows in chain.groupby("ts", sort=True)
    }


def strict_slice(moment: str | pd.Timestamp, day: date = ANCHOR) -> pd.DataFrame:
    """Every quote stamped at **one** minute - the latest minute at or before `moment`."""
    chain = load_chain(day)
    stamps = chain.ts[chain.ts <= pd.Timestamp(moment)]
    if stamps.empty:
        raise StrikeNotQuoted(0.0, "--")
    return chain[chain.ts == stamps.iloc[-1]]


def forward_at(moment: str | pd.Timestamp, day: date = ANCHOR) -> forward_maths.ForwardFit:
    """The fit for the latest minute at or before `moment`, off the day's one pass."""
    stamp = strict_slice(moment, day).ts.iloc[0]
    return fits(day)[stamp]


def attainable(price, forward, strike, T, discount, *, is_call) -> np.ndarray:
    """Which prices some volatility actually reproduces, asked before Newton is asked.

    `implied_vol` raises when a row does not solve, and it is right to: handing back the
    edge of the search would put a plausible curve on a screen (ADR-0001). But it raises
    for the **whole array**, and across twenty-four dates a handful of rows genuinely
    admit no volatility - a print below discounted intrinsic reproduces at no positive
    sigma, and at Expiry the price does not depend on sigma at all. Losing a day to one
    of those would be the wrong trade.

    So the same question `implied_vol` answers at the end is asked here at the start, in
    the same terms: the price is monotone in volatility, so it is attainable exactly when
    it lies between the two ends of the search bracket. A row that fails this carries no
    volatility - `NaN` here, `null` on the wire - and a row that passes and still fails to
    converge is a solver bug and still raises.
    """
    low, high = pricing.VOL_SEARCH_BRACKET
    floor = pricing.black76_price(forward, strike, T, low, discount, is_call=is_call)
    ceiling = pricing.black76_price(forward, strike, T, high, discount, is_call=is_call)
    return (
        (np.asarray(T, dtype=float) > 0.0)
        & (price >= floor - pricing.VOL_TOLERANCE)
        & (price <= ceiling + pricing.VOL_TOLERANCE)
    )


@lru_cache(maxsize=4)
def solved_volatility(day: date = ANCHOR) -> pd.Series:
    """One volatility per strike per minute, solved rather than read (#52).

    Indexed by `(ts, strike)` and **not** by side, because that is what an implied
    volatility is here: the source carries one number per strike and hands it to both
    legs, which is why the interface shows a single centred column rather than two.

    Which leg is inverted follows `docs/calculations.md` section 4 and the measurement
    behind it:

    - the **out-of-the-money** leg - the call when `K >= F_hat`, the put when `K < F_hat`
      - because the in-the-money print is the stale one;
    - failing that, whichever leg *is* quoted. On 392 strike-minutes of the anchor only
      the in-the-money side printed, and the source solves those from that print rather
      than leaving them blank. Skipping them would blank the strike for every later
      moment too, since the chain is served as-of.

    "Quoted" became "quoted **and** invertible" with #67, which widened the build to
    dates the anchor's rule had never met. A print below discounted intrinsic reproduces
    at no volatility at all, and where that print is the out-of-the-money one the rule
    falls through to the other side rather than blanking the strike - which is the same
    fallback, one step further down.

    **Each quote is inverted in its own minute**, against that minute's forward and
    discount, never against the requested moment's. Served as-of, a print can be 153
    minutes older than the forward beside it in the response; inverting it against a
    forward that has moved a hundred points since measures the drift, not the volatility.

    Solved for the whole day at once. It costs 29.5 ms - one vectorised Newton sweep set
    over the anchor's 18,994 rows - which is cheaper than the caching a per-moment solve
    would need in order to avoid it.
    """
    chain = load_chain(day)
    fit = fits(day)
    forward = chain.ts.map(lambda stamp: fit[stamp].forward).to_numpy(float)
    discount = chain.ts.map(lambda stamp: fit[stamp].discount).to_numpy(float)
    strike = chain.strike.to_numpy(float)
    is_call = (chain.option_type == "CE").to_numpy()
    T = chain.dte_days.to_numpy(float) / TRADING_DAYS_PER_YEAR
    price = chain["last"].to_numpy(float)

    solvable = np.zeros(len(chain), dtype=bool)
    for call in (True, False):
        rows = is_call == call
        solvable[rows] = attainable(
            price[rows], forward[rows], strike[rows], T[rows], discount[rows], is_call=call
        )

    out_of_money = np.where(is_call, strike >= forward, strike < forward) & solvable
    at = pd.MultiIndex.from_arrays([chain.ts, chain.strike])
    invert = out_of_money | (solvable & ~at.isin(at[out_of_money]))

    volatility = np.empty(int(invert.sum()), dtype=float)
    for call in (True, False):
        side = (is_call == call)[invert]
        rows = invert & (is_call == call)
        volatility[side] = implied_vol(
            price[rows], forward[rows], strike[rows], T[rows], discount[rows], is_call=call
        )

    return pd.Series(volatility, index=at[invert], name="iv")


@lru_cache(maxsize=4)
def solved_chain(day: date = ANCHOR) -> pd.DataFrame:
    """The day's quotes with the volatility this engine solved for itself.

    A strike whose volatility did not solve carries `NaN` and reaches the wire as `null`
    (ADR-0001 bans NaN there). On the anchor every quoted strike solves; on Expiry day
    the final minute solves none of them, because at `T = 0` the price no longer depends
    on volatility and there is nothing for Newton to invert.
    """
    chain = load_chain(day)
    return chain.assign(iv=pd.MultiIndex.from_arrays([chain.ts, chain.strike])
                        .map(solved_volatility(day)))

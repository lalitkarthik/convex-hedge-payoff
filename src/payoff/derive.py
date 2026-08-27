"""Deriving the day - everything the store is built from, and nothing that serves it.

The engine derives every number it publishes: the Forward and the Discount Factor by
put-call parity (#51), the volatility by Newton (#52), the Greeks from Black-76 (#53).
On the sample day the first two cost **1.4 s**, and until #66 every process paid that at
start-up, for a day that had already happened and could not change.

So the two halves are now separate modules. **This one solves.** It reads the committed
seed, `Data/sample/chain_2026-01-27.parquet`, which is already the product of the IST/UTC
join documented in `docs/data-quality.md`, and it is imported by `scripts/build_runtime.py`
and by `tests/test_implied_vol.py` and by nothing else. **`chain.py` reads**, from the
partitioned store the build writes. Nothing in the serving path imports this module, which
is precisely what turns the 1.4 s from a boot cost into a build cost.

The Oracle direction is unchanged, and it is why `load_chain()` drops the graded columns
*here*, on the way in, rather than in the writer: what reaches the store is the engine's
own answer, and a column that cannot be read cannot be read by accident. CONTEXT.md:138.
"""

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from payoff import forward as forward_maths
from payoff.chain import StrikeNotQuoted
from payoff.pricing import TRADING_DAYS_PER_YEAR, implied_vol

SAMPLE_FILE = Path(__file__).resolve().parents[2] / "Data" / "sample" / "chain_2026-01-27.parquet"
"""The committed seed. Not the runtime data - `store.runtime_root()` is that, and #66
made the difference load-bearing rather than nominal."""


#: Solved upstream and shipped in the file. The engine derives every one of them itself -
#: the forward and discount in #51, the volatility in #52, the Greeks in #53 - and is
#: graded against these columns in `tests/test_forward.py`, `tests/test_implied_vol.py`
#: and `tests/test_oracle.py`. They are dropped at load: an answer that cannot be read
#: cannot be read by accident.
#:
#: `vanna`, `volga` and `charm` are dropped with the rest despite nothing deriving them.
#: A column that survives the cull is a column something may quietly start serving.
ORACLE_COLUMNS = (
    "forward", "discount", "iv",
    "delta", "gamma", "theta", "vega", "rho", "vanna", "volga", "charm",
)


@lru_cache(maxsize=1)
def load_chain() -> pd.DataFrame:
    """Load the committed seed once, for the build's lifetime."""
    chain = pd.read_parquet(SAMPLE_FILE).sort_values("ts").reset_index(drop=True)
    return chain.drop(columns=list(ORACLE_COLUMNS))


@lru_cache(maxsize=512)
def strict_slice(moment: str | pd.Timestamp) -> pd.DataFrame:
    """Every quote stamped at **one** minute - the latest minute at or before `moment`.

    A *fit* is run strictly because the as-of view mixes quote ages up to 153 minutes
    apart, and the regression's slope is the Discount Factor. Stale prints would land in
    it directly.
    """
    chain = load_chain()
    stamps = chain.ts[chain.ts <= pd.Timestamp(moment)]
    if stamps.empty:
        raise StrikeNotQuoted(0.0, "--")
    return chain[chain.ts == stamps.iloc[-1]]


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


@lru_cache(maxsize=512)
def forward_at(moment: str | pd.Timestamp) -> forward_maths.ForwardFit:
    """The Forward and Discount Factor this moment implies (#51).

    Slices the minute and hands `forward.fit_forward` arrays; the maths never sees a
    chain. The result names the tier that produced it, because on 60 of this day's 376
    minutes the regression cannot be trusted and the answer is assumed rather than
    measured.

    This is the expensive half of the 1.4 s, and it runs in the build.
    `chain.forward_at` reads the answer back off the row the build wrote.
    """
    rows = strict_slice(moment)
    paired = paired_quotes(rows)
    return forward_maths.fit_forward(
        strikes=paired.index.to_numpy(float),
        calls=paired.CE.to_numpy(float),
        puts=paired.PE.to_numpy(float),
        quoted_strikes=rows.strike.unique(),
        T=float(rows.dte_days.iloc[0]) / TRADING_DAYS_PER_YEAR,
        spot=float(rows.spot.iloc[0]),
    )


@lru_cache(maxsize=1)
def solved_volatility() -> pd.Series:
    """One volatility per strike per minute, solved rather than read (#52).

    Indexed by `(ts, strike)` and **not** by side, because that is what an implied
    volatility is here: the source carries one number per strike and hands it to both
    legs, which is why the interface shows a single centred column rather than two.

    Which leg is inverted follows `docs/calculations.md` section 4 and the measurement
    behind it:

    - the **out-of-the-money** leg - the call when `K >= F_hat`, the put when `K < F_hat`
      - because the in-the-money print is the stale one;
    - failing that, whichever leg *is* quoted. On 392 strike-minutes only the in-the-money
      side printed, and the source solves those from that print rather than leaving them
      blank. Skipping them would blank the strike for every later moment too, since the
      chain is served as-of.

    **Each quote is inverted in its own minute**, against that minute's forward and
    discount, never against the requested moment's. Served as-of, a print can be 153
    minutes older than the forward beside it in the response; inverting it against a
    forward that has moved a hundred points since measures the drift, not the volatility.

    Solved for the whole day at once. It costs 29.5 ms - one vectorised Newton sweep set
    over 18,994 rows - which is cheaper than the caching a per-moment solve would need in
    order to avoid it.
    """
    chain = load_chain()
    fits = {stamp: forward_at(stamp) for stamp in chain.ts.unique()}
    forward = chain.ts.map(lambda stamp: fits[stamp].forward).to_numpy(float)
    discount = chain.ts.map(lambda stamp: fits[stamp].discount).to_numpy(float)
    strike = chain.strike.to_numpy(float)
    is_call = (chain.option_type == "CE").to_numpy()
    T = chain.dte_days.to_numpy(float) / TRADING_DAYS_PER_YEAR

    out_of_money = np.where(is_call, strike >= forward, strike < forward)
    at = pd.MultiIndex.from_arrays([chain.ts, chain.strike])
    invert = out_of_money | ~at.isin(at[out_of_money])

    volatility = np.empty(int(invert.sum()), dtype=float)
    for call in (True, False):
        side = (is_call == call)[invert]
        rows = invert & (is_call == call)
        volatility[side] = implied_vol(
            chain["last"].to_numpy(float)[rows],
            forward[rows],
            strike[rows],
            T[rows],
            discount[rows],
            is_call=call,
        )

    return pd.Series(volatility, index=at[invert], name="iv")


@lru_cache(maxsize=1)
def solved_chain() -> pd.DataFrame:
    """The seed frame with the volatility this engine solved for itself.

    The `iv` column here is not the one the file shipped - that one is dropped at load.
    A strike whose volatility did not solve carries `NaN` and reaches the wire as `null`
    (ADR-0001 bans NaN there); on this day every quoted strike solves.
    """
    chain = load_chain()
    return chain.assign(iv=pd.MultiIndex.from_arrays([chain.ts, chain.strike])
                        .map(solved_volatility()))


def expiry_label() -> str:
    """The Expiry this seed contains, read off the instrument name.

    'NIFTY10FEB2623350PE.NFO' -> '10FEB26'. `build_runtime.expiry_date()` turns that into
    the sortable `expiry=2026-02-10` the partition key wants, and `chain.expiry_label()`
    formats it back from that key - so the label a trader reads is now the one the tree
    was written under rather than a string only this module can see.
    """
    ticker = str(load_chain().Ticker.iloc[0])
    return ticker.removeprefix("NIFTY")[:7]

"""Chain loading and the as-of view.

Runtime data is **one derived file loaded into memory at boot** - not the three raw
files, and not a database (#23). The file is `Data/sample/chain_2026-01-27.parquet`,
which is already the product of the IST/UTC join documented in `docs/data-quality.md`.
Widening it beyond one day is a matter of regenerating that file; nothing in this
module's interface changes.

**The Chain is served as-of.** Only strikes that actually traded in a given minute have
a bar, so a strict reading of "the Chain at this moment" is much thinner than a trader
expects - the last known quote at or before the moment is what makes a usable chain.
#28 owns the shape that view is published in, and the measurements behind it.

The core never sees a Chain. A strike absent from it raises **here** (#23).
"""

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from payoff import forward as forward_maths
from payoff.models import ChainQuote, ChainResponse, ChainRow, Leg, LegRequest
from payoff.pricing import TRADING_DAYS_PER_YEAR, black76_greeks, implied_vol

RUNTIME_FILE = Path(__file__).resolve().parents[2] / "Data" / "sample" / "chain_2026-01-27.parquet"


class StrikeNotQuoted(LookupError):
    """A strike with no quote at or before the requested moment.

    Carries the strike so the interface can name it rather than showing a blank chart.
    #31 owns what a caller sees when this happens.
    """

    def __init__(self, strike: float, option_type: str) -> None:
        self.strike = strike
        self.option_type = option_type
        super().__init__(f"{strike:.0f} {option_type} is not quoted at or before this moment")


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
    """Load the runtime file once, at boot, and keep it for the process's lifetime."""
    chain = pd.read_parquet(RUNTIME_FILE).sort_values("ts").reset_index(drop=True)
    return chain.drop(columns=list(ORACLE_COLUMNS))


@lru_cache(maxsize=512)
def strict_slice(moment: str | pd.Timestamp) -> pd.DataFrame:
    """Every quote stamped at **one** minute - the latest minute at or before `moment`.

    The counterpart to `snapshot()`, and not a substitute for it. A chain is served
    as-of because a strict reading of it is too thin to trade from; a *fit* is run
    strictly because the as-of view mixes quote ages up to 153 minutes apart, and the
    regression's slope is the Discount Factor. Stale prints would land in it directly.
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
    calls this for every minute of the day at once, which turned that into 1.8 seconds;
    every `/chain` request was already paying one of them.
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

    Solved for the whole day at once, on first use. It costs 29.5 ms - one vectorised
    Newton sweep set over 18,994 rows - which is cheaper than the caching a per-moment
    solve would need in order to avoid it.
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
    """The runtime frame with the volatility this engine solved for itself.

    The `iv` column here is not the one the file shipped - that one is dropped at load.
    A strike whose volatility did not solve carries `NaN` and reaches the wire as `null`
    (ADR-0001 bans NaN there); on this day every quoted strike solves.
    """
    chain = load_chain()
    return chain.assign(iv=pd.MultiIndex.from_arrays([chain.ts, chain.strike])
                        .map(solved_volatility()))


@lru_cache(maxsize=256)
def snapshot(moment: str | pd.Timestamp) -> pd.DataFrame:
    """The Chain as-of `moment`: the last known quote for every strike at or before it.

    Every row carries `age_minutes`. On the sample day the median quote is one minute
    old while the wings reach 153, and presenting the second as live would be dishonest
    rather than merely imprecise.

    Cached per moment: the runtime file is immutable for the life of the process, so
    the same minute cannot produce two different snapshots. Callers treat the frame as
    read-only. Building one costs 5.5 ms - not the 0.258 ms #23 measured for a
    searchsorted index, but still an order of magnitude inside the round trip it saves,
    and the cache takes a repeat to microseconds.
    """
    moment = pd.Timestamp(moment)
    at_or_before = solved_chain()[lambda chain: chain.ts <= moment]
    latest = at_or_before.groupby(["strike", "option_type"], as_index=False).last()

    age = (moment - latest.ts).dt.total_seconds() // 60

    # Implied volatility is a property of the STRIKE, not of the side. Served as-of,
    # a call and its put can be minutes apart: of the 41 both-sided strikes at the
    # anchor minute only 9 share a minute, and the rest disagree by up to 0.0275. The
    # one that belongs to the strike is the freshest of the two.
    freshest = latest.sort_values("ts").groupby("strike").iv.last()

    quotes = latest.assign(
        age_minutes=age.astype("int64"),
        strike_iv=latest.strike.map(freshest).astype(float),
    )

    # Delta is **computed**, never read (#53). It is priced at the moment being asked
    # about - this minute's forward, discount and T - and at the strike's one shared
    # volatility, not at whatever minute each side last printed in. A delta is a property
    # of the model now, not of when a print happened to land; pricing the two sides in
    # two different minutes gives a call and a put whose deltas do not even satisfy
    # parity, which is what the file's own columns do here.
    fit = forward_at(moment)
    delta = np.empty(len(quotes), dtype=float)
    for call in (True, False):
        side = (quotes.option_type == "CE").to_numpy() == call
        if not side.any():
            continue
        delta[side] = black76_greeks(
            fit.forward,
            quotes.strike.to_numpy(float)[side],
            fit.T,
            quotes.strike_iv.to_numpy(float)[side],
            fit.discount,
            is_call=call,
        )["delta"]
    return quotes.assign(delta=delta)


def spot_at(moment: str | pd.Timestamp) -> float:
    """The NIFTY level at the moment - what the header shows and the x-axis measures."""
    rows = load_chain()[lambda chain: chain.ts <= pd.Timestamp(moment)]
    if rows.empty:
        raise StrikeNotQuoted(0.0, "--")
    return float(rows.spot.iloc[-1])


def at_the_money(moment: str | pd.Timestamp) -> float:
    """The quoted strike nearest the **Forward** (#51).

    Not nearest Spot. The basis runs to +118.87 at the anchor minute, which is more than
    two 50-point intervals, so the two anchors select different strikes - 25,200 against
    25,100 - and every Preset centred here moves with it. Spot is where the index is; the
    Forward is what the options are priced off, and the money is a fact about the options.

    Nearest **quoted** strike rather than the arithmetic answer rounded to the grid: on a
    thin minute the arithmetic answer may not be quoted at all, and a Preset that opens
    with an unquoted Leg is worse than one that opens a strike away.

    Chosen among strikes quoting both sides, which is the same set the fit ran on. Where
    that set is empty - at the close, nothing quotes both - the choice widens to every
    strike quoted that minute rather than failing: a coarser answer beats none.
    """
    rows = strict_slice(moment)
    paired = paired_quotes(rows)
    candidates = (
        paired.index.to_numpy(float) if len(paired) else np.sort(rows.strike.unique())
    )
    if not len(candidates):
        raise StrikeNotQuoted(0.0, "--")
    return float(candidates[np.abs(candidates - forward_at(moment).forward).argmin()])


def resolve_legs(requests: list[LegRequest], moment: str | pd.Timestamp) -> list[Leg]:
    """Turn what the client asked for into Legs the engine can price.

    This is where implied volatility enters the system - **looked up, never accepted
    from the client**. A client that posted a wrong value would get a plausible-looking
    wrong chart that nothing else would catch.

    Entry Premium is the Chain's last traded price unless the client overrode it
    (story 18), which is the one price a trader legitimately supplies.
    """
    quotes = snapshot(moment).set_index(["strike", "option_type"])

    legs = []
    for request in requests:
        key = (request.strike, request.option_type)
        if key not in quotes.index:
            raise StrikeNotQuoted(request.strike, request.option_type)
        quote = quotes.loc[key]

        legs.append(
            Leg(
                strike=request.strike,
                option_type=request.option_type,
                direction=request.direction,
                quantity=request.quantity,
                entry_premium=(
                    float(quote["last"]) if request.entry_premium is None
                    else float(request.entry_premium)
                ),
                iv=float(quote["strike_iv"]),
            )
        )
    return legs


def expiry_label() -> str:
    """The single Expiry this dataset contains, read off the instrument name.

    'NIFTY10FEB2623350PE.NFO' -> '10FEB26'. There is exactly one, which is why the
    header shows text rather than a dropdown.
    """
    ticker = str(load_chain().Ticker.iloc[0])
    return ticker.removeprefix("NIFTY")[:7]


@lru_cache(maxsize=1)
def moments() -> list[str]:
    """Every minute a client may ask for, in session order.

    **Derived from the data, never from a clock.** 09:15 to 15:30 IST is 376 minutes
    here rather than the 376 a clock would give only by coincidence of this day; a
    minute in which nothing quoted has no bar, and offering it as a stop on the time
    control would hand a trader a slider position that returns an empty Chain.

    **ISO 8601**, with the `T`, which is also what `as_of_view` echoes back. Pandas
    parses `2026-01-27 06:30:00` and `2026-01-27T06:30:00` alike, so the two spellings
    are interchangeable on the way *in* and were free to differ on the way out - and a
    client that compares the moment on a Chain against the entry it asked for would have
    found them unequal every single time, with nothing to see on screen. One spelling
    out, and it is the one `Date` is specified to parse.
    """
    return [pd.Timestamp(stamp).isoformat() for stamp in load_chain().ts.unique()]


@lru_cache(maxsize=1)
def strike_bounds() -> tuple[float, float]:
    """The lowest and highest strike quoted anywhere in the session.

    The day's range, not a minute's: a single minute quotes fewer strikes than the day
    does, and an axis that resized as the trader moved through time would make two
    charts of the same Strategy incomparable.
    """
    strikes = load_chain().strike
    return float(strikes.min()), float(strikes.max())


def as_of_view(moment: str | pd.Timestamp) -> ChainResponse:
    """The Chain a trader sees: one row per strike, call and put either side.

    Served as-of, because a strict reading of "the Chain at this moment" is nine
    strikes quoting both sides out of the ninety-four in the file - and on some minutes
    of this day, none at all. The last known quote at or before the moment gives 41.
    """
    sides: dict[float, dict[str, ChainQuote]] = {}
    strike_iv: dict[float, float] = {}
    for quote in snapshot(moment).to_dict("records"):
        strike_iv[float(quote["strike"])] = float(quote["strike_iv"])
        side = "call" if quote["option_type"] == "CE" else "put"
        sides.setdefault(float(quote["strike"]), {})[side] = ChainQuote(
            last=float(quote["last"]),
            open_interest=float(quote["OpenInterest"]),
            volume=float(quote["Volume"]),
            delta=float(quote["delta"]),
            age_minutes=int(quote["age_minutes"]),
        )

    rows = [
        ChainRow(
            strike=strike,
            iv=strike_iv.get(strike),
            call=sides[strike].get("call"),
            put=sides[strike].get("put"),
        )
        for strike in sorted(sides)
    ]
    fit = forward_at(moment)
    return ChainResponse(
        moment=pd.Timestamp(moment).isoformat(),
        spot=spot_at(moment),
        expiry=expiry_label(),
        forward=fit.forward,
        discount=fit.discount,
        forward_method=fit.method,
        rows=rows,
    )

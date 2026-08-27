"""Chain loading and the as-of view.

Runtime data is the **partitioned store**, read through `store.scan` (#66) - not one
derived file loaded into memory at boot, and not a database (#23). What was a
`pd.read_parquet` at import time is now a `pl.LazyFrame`: a query plan, not rows. Every
function below composes its filter and its projection onto that plan and collects only
what it asked for, so an as-of query at 12:00 reads neither the afternoon's row groups
nor the columns it did not name.

**Nothing here solves any more.** The Forward, the Discount Factor and the volatility are
read off the row `scripts/build_runtime.py` wrote; deriving them is `derive.py`'s job and
it happens once, in the build. That is the 1.4 s this module used to pay on the first
request of every process, for a day that had already happened and could not change.

Delta is the exception, and deliberately so: it is **computed on every request** (#53),
because it is a property of the model at the moment being asked about rather than a fact
about a print. It costs one vectorised Black-76 call over the ninety-odd strikes in view.

**The Chain is served as-of.** Only strikes that actually traded in a given minute have
a bar, so a strict reading of "the Chain at this moment" is much thinner than a trader
expects - the last known quote at or before the moment is what makes a usable chain.
#28 owns the shape that view is published in, and the measurements behind it.

The core never sees a Chain. A strike absent from it raises **here** (#23).
"""

from datetime import date, datetime
from functools import lru_cache

import numpy as np
import polars as pl

from payoff import forward as forward_maths
from payoff import store
from payoff.models import ChainQuote, ChainResponse, ChainRow, Leg, LegRequest
from payoff.pricing import TRADING_DAYS_PER_YEAR, black76_greeks

ANCHOR_DATE = date(2026, 1, 27)
"""The one date the build writes and this module serves.

A constant rather than a parameter because #66 is deliberately invisible: the store can
already hold any number of days, `scripts/build_runtime.py` still derives exactly one, and
no new day becomes reachable until #67 widens the build and #68 gives a client a way to
ask for one. Until then this filter is what makes that promise structural rather than
incidental - it reaches the parquet reader as a partition predicate, so a stray second
day under the tree would be skipped rather than silently merged into this one.
"""

MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
"""Spelled out rather than left to `strftime('%b')`, which is locale-dependent: the Expiry
label is asserted as `10FEB26` and a machine set to fr_FR would serve `10FÉVR.26`."""


class StrikeNotQuoted(LookupError):
    """A strike with no quote at or before the requested moment.

    Carries the strike so the interface can name it rather than showing a blank chart.
    #31 owns what a caller sees when this happens.
    """

    def __init__(self, strike: float, option_type: str) -> None:
        self.strike = strike
        self.option_type = option_type
        super().__init__(f"{strike:.0f} {option_type} is not quoted at or before this moment")


class MissingRuntimeTree(RuntimeError):
    """No derived data where the serving path was told to look.

    Raised loudly, at the first read, rather than quietly re-deriving from the committed
    sample. A fallback would put the 1.4 s back into the request path - the exact cost
    #64 exists to remove - and it would hide a misconfigured deployment behind an answer
    that looked right. `tests/conftest.py` runs the build for the suite; a deployment runs
    it in its release step.
    """


@lru_cache(maxsize=1)
def chain_scan() -> pl.LazyFrame:
    """The lazy plan every read below is composed onto.

    Cached because building the plan globs the tree, not because it holds rows - it holds
    none. Collecting it twice reads the parquet twice, which is the point: the filter goes
    to the reader rather than to a frame already in memory.
    """
    root = store.runtime_root()
    dataset = store.dataset_root(root)
    if not dataset.exists():
        raise MissingRuntimeTree(
            f"No derived chain at {dataset}. Run `python scripts/build_runtime.py` to "
            "derive it from the committed sample, or point PAYOFF_RUNTIME at a tree that "
            "has already been built."
        )
    return store.scan(root).filter(pl.col("date") == ANCHOR_DATE)


def _at(moment: str | datetime) -> datetime:
    """One spelling of a moment, whatever the caller handed in.

    `2026-01-27 06:30:00` and `2026-01-27T06:30:00` both parse, which is what the wire
    accepted before and what `moments()` has to keep echoing back unchanged.
    """
    return moment if isinstance(moment, datetime) else datetime.fromisoformat(str(moment))


@lru_cache(maxsize=512)
def strict_slice(moment: str | datetime) -> pl.DataFrame:
    """Every quote stamped at **one** minute - the latest minute at or before `moment`.

    The counterpart to `snapshot()`, and not a substitute for it. A chain is served
    as-of because a strict reading of it is too thin to trade from; the Forward, the
    Discount Factor and the at-the-money strike are read strictly, because they are
    facts about a minute rather than about a strike's last print.
    """
    rows = (
        chain_scan()
        .filter(pl.col("timestamp_utc") <= _at(moment))
        .filter(pl.col("timestamp_utc") == pl.col("timestamp_utc").max())
        .collect()
    )
    if rows.is_empty():
        raise StrikeNotQuoted(0.0, "--")
    return rows


def paired_strikes(rows: pl.DataFrame) -> np.ndarray:
    """The strikes quoting **both** sides in one minute, sorted.

    Parity is an identity about a call and its put at one strike, so a strike quoting
    only one side has nothing to say and is dropped rather than half-used. This is the
    same set `derive.paired_quotes` fits the regression over, which is why the count it
    returns is the `pairs` a stored fit can be reconstructed with.
    """
    calls = rows.filter(pl.col("option_type") == "CE")["strike"].to_numpy()
    puts = rows.filter(pl.col("option_type") == "PE")["strike"].to_numpy()
    return np.intersect1d(calls, puts)


@lru_cache(maxsize=512)
def forward_at(moment: str | datetime) -> forward_maths.ForwardFit:
    """The Forward and Discount Factor this moment implies (#51) - **read, not fitted**.

    The regression ran in the build, once per minute, and its answer is on every row of
    that minute along with the tier that produced it. Reading it back is not a shortcut
    past #51: the number is the engine's own, and `build_runtime.py --check` re-derives
    the whole day and compares, so a tree written by older code is caught rather than
    served.

    `pairs` is the one field of the fit the store does not carry, and it is recovered
    rather than invented - it is the size of the both-sided set, which is in the minute.
    """
    rows = strict_slice(moment)
    return forward_maths.ForwardFit(
        forward=float(rows["forward"][0]),
        discount=float(rows["discount"][0]),
        T=float(rows["dte_days"][0]) / TRADING_DAYS_PER_YEAR,
        method=str(rows["forward_method"][0]),
        pairs=int(paired_strikes(rows).size),
    )


@lru_cache(maxsize=256)
def snapshot(moment: str | datetime) -> pl.DataFrame:
    """The Chain as-of `moment`: the last known quote for every strike at or before it.

    Every row carries `age_minutes`. On the sample day the median quote is one minute
    old while the wings reach 153, and presenting the second as live would be dishonest
    rather than merely imprecise.

    Cached per moment: the store is immutable for the life of the process, so the same
    minute cannot produce two different snapshots. Callers treat the frame as read-only.
    """
    at = _at(moment)
    latest = (
        chain_scan()
        .filter(pl.col("timestamp_utc") <= at)
        .sort("timestamp_utc")
        .group_by("strike", "option_type", maintain_order=True)
        .last()
        .sort("timestamp_utc")
        # Implied volatility is a property of the STRIKE, not of the side. Served as-of,
        # a call and its put can be minutes apart: of the 41 both-sided strikes at the
        # anchor minute only 9 share a minute, and the rest disagree by up to 0.0275. The
        # one that belongs to the strike is the freshest of the two.
        .with_columns(pl.col("iv").last().over("strike").alias("strike_iv"))
        .with_columns(
            (pl.lit(at) - pl.col("timestamp_utc")).dt.total_minutes().alias("age_minutes")
        )
        .sort("strike", "option_type")
        .collect()
    )
    if latest.is_empty():
        raise StrikeNotQuoted(0.0, "--")

    # Delta is **computed**, never read (#53). It is priced at the moment being asked
    # about - this minute's forward, discount and T - and at the strike's one shared
    # volatility, not at whatever minute each side last printed in. A delta is a property
    # of the model now, not of when a print happened to land; pricing the two sides in
    # two different minutes gives a call and a put whose deltas do not even satisfy
    # parity, which is what the source file's own columns do here.
    fit = forward_at(moment)
    is_call = (latest["option_type"] == "CE").to_numpy()
    strikes = latest["strike"].to_numpy()
    volatility = latest["strike_iv"].to_numpy()

    delta = np.empty(latest.height, dtype=float)
    for call in (True, False):
        side = is_call == call
        if not side.any():
            continue
        delta[side] = black76_greeks(
            fit.forward,
            strikes[side],
            fit.T,
            volatility[side],
            fit.discount,
            is_call=call,
        )["delta"]
    return latest.with_columns(delta=pl.Series("delta", delta))


def spot_at(moment: str | datetime) -> float:
    """The NIFTY level at the moment - what the header shows.

    Off the strict minute rather than off the last row of the day up to here, which is
    the same number: Spot is observed once per minute and repeats across every strike in
    it, which is why #64 moves it into a summary artifact of its own.
    """
    return float(strict_slice(moment)["spot"][0])


def at_the_money(moment: str | datetime) -> float:
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
    paired = paired_strikes(rows)
    candidates = paired if paired.size else np.sort(rows["strike"].unique().to_numpy())
    if not len(candidates):
        raise StrikeNotQuoted(0.0, "--")
    return float(candidates[np.abs(candidates - forward_at(moment).forward).argmin()])


def resolve_legs(requests: list[LegRequest], moment: str | datetime) -> list[Leg]:
    """Turn what the client asked for into Legs the engine can price.

    This is where implied volatility enters the system - **looked up, never accepted
    from the client**. A client that posted a wrong value would get a plausible-looking
    wrong chart that nothing else would catch.

    Entry Premium is the Chain's last traded price unless the client overrode it
    (story 18), which is the one price a trader legitimately supplies.
    """
    quotes = {
        (quote["strike"], quote["option_type"]): quote
        for quote in snapshot(moment).iter_rows(named=True)
    }

    legs = []
    for request in requests:
        key = (request.strike, request.option_type)
        if key not in quotes:
            raise StrikeNotQuoted(request.strike, request.option_type)
        quote = quotes[key]

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


@lru_cache(maxsize=1)
def expiry_label() -> str:
    """The single Expiry this dataset contains, formatted off the **partition key**.

    `expiry=2026-02-10` -> `10FEB26`. It used to be read off an instrument name inside
    the file; now it comes from the path the tree was written under, which is the one
    place a second Expiry would ever announce itself. There is exactly one, which is why
    the header shows text rather than a dropdown.
    """
    expiry = chain_scan().select(pl.col("expiry").first()).collect().item()
    return f"{expiry.day:02d}{MONTHS[expiry.month - 1]}{expiry.year % 100:02d}"


@lru_cache(maxsize=1)
def moments() -> list[str]:
    """Every minute a client may ask for, in session order.

    **Derived from the data, never from a clock.** 09:15 to 15:30 IST is 376 minutes
    here rather than the 376 a clock would give only by coincidence of this day; a
    minute in which nothing quoted has no bar, and offering it as a stop on the time
    control would hand a trader a slider position that returns an empty Chain.

    **ISO 8601**, with the `T`, which is also what `as_of_view` echoes back. Both
    spellings parse on the way *in* and were free to differ on the way out - and a client
    that compares the moment on a Chain against the entry it asked for would have found
    them unequal every single time, with nothing to see on screen. One spelling out, and
    it is the one `Date` is specified to parse.
    """
    stamps = (
        chain_scan().select("timestamp_utc").unique().sort("timestamp_utc").collect()
    )
    return [stamp.isoformat() for stamp in stamps["timestamp_utc"]]


@lru_cache(maxsize=1)
def strike_bounds() -> tuple[float, float]:
    """The lowest and highest strike quoted anywhere in the session.

    The day's range, not a minute's: a single minute quotes fewer strikes than the day
    does, and an axis that resized as the trader moved through time would make two
    charts of the same Strategy incomparable.
    """
    low, high = (
        chain_scan()
        .select(pl.col("strike").min().alias("low"), pl.col("strike").max().alias("high"))
        .collect()
        .row(0)
    )
    return float(low), float(high)


def as_of_view(moment: str | datetime) -> ChainResponse:
    """The Chain a trader sees: one row per strike, call and put either side.

    Served as-of, because a strict reading of "the Chain at this moment" is nine
    strikes quoting both sides out of the ninety-four in the store - and on some minutes
    of this day, none at all. The last known quote at or before the moment gives 41.
    """
    sides: dict[float, dict[str, ChainQuote]] = {}
    strike_iv: dict[float, float] = {}
    for quote in snapshot(moment).iter_rows(named=True):
        strike_iv[float(quote["strike"])] = float(quote["strike_iv"])
        side = "call" if quote["option_type"] == "CE" else "put"
        sides.setdefault(float(quote["strike"]), {})[side] = ChainQuote(
            last=float(quote["last"]),
            open_interest=float(quote["open_interest"]),
            volume=float(quote["volume"]),
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
        moment=_at(moment).isoformat(),
        spot=spot_at(moment),
        expiry=expiry_label(),
        forward=fit.forward,
        discount=fit.discount,
        forward_method=fit.method,
        rows=rows,
    )

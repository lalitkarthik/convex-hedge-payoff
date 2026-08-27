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

**Nor does anything here carry a quote forward any more (#67).** The stored Chain holds
every minute for every strike with the last known quote already carried across, so the
as-of view is a slice of one minute rather than a group-by over everything up to it. The
work it replaced ran on every request and 376 times over while a trader dragged the time
control.

Delta is the exception, and deliberately so: it is **computed on every request** (#53),
because it is a property of the model at the moment being asked about rather than a fact
about a print. It costs one vectorised Black-76 call over the ninety-odd strikes in view.

**Every read takes a date.** Until #67 the store held one, and this module filtered to it
by a constant. Now it holds twenty-four, and the date comes from the request - either
explicitly or off the moment, which already carries one. `ANCHOR_DATE` survives as the
default for the session endpoint, which has no moment to read one from; #68 makes the
date a thing a trader picks.

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
"""The date served when a caller names none.

Every published figure in `docs/calculations.md` was measured on it, and `/session` still
describes it, because a session is a day and until #68 there is no control that would let
a trader say which. It is no longer a filter that makes a promise structural: #67 built
the other twenty-three and `/chain` reaches them.
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

    Raised loudly, at the first read, rather than quietly re-deriving from the raw files.
    A fallback would put the derivation back into the request path - the exact cost #64
    exists to remove - and it would hide a misconfigured deployment behind an answer that
    looked right. `tests/conftest.py` runs the build for the suite; a deployment runs it
    in its release step.
    """


def _at(moment: str | datetime) -> datetime:
    """One spelling of a moment, whatever the caller handed in.

    `2026-01-27 06:30:00` and `2026-01-27T06:30:00` both parse, which is what the wire
    accepted before and what `moments()` has to keep echoing back unchanged.
    """
    return moment if isinstance(moment, datetime) else datetime.fromisoformat(str(moment))


def _on(moment: str | datetime, day: str | date | None = None) -> date:
    """Which trading date a request is about.

    Off the moment when the caller named no date, because the moment already carries one
    and the two cannot disagree: the session runs 09:15 to 15:30 IST, which is 03:45 to
    10:00 UTC, so a session never crosses a UTC midnight and the calendar date is the
    same in both zones. The explicit parameter exists because a date is what the tree is
    keyed by and what a URL will carry (#68), not because it can say something the moment
    could not.
    """
    if day is None:
        return _at(moment).date()
    return day if isinstance(day, date) else date.fromisoformat(str(day))


@lru_cache(maxsize=32)
def chain_scan(day: date = ANCHOR_DATE) -> pl.LazyFrame:
    """The lazy plan every read below is composed onto, filtered to one date.

    Cached because building the plan globs the tree, not because it holds rows - it holds
    none. Collecting it twice reads the parquet twice, which is the point: the filter
    goes to the reader rather than to a frame already in memory, and the date reaches it
    as a **partition predicate**, so the other twenty-three days are skipped before a
    byte of column data is read.
    """
    root = store.runtime_root()
    dataset = store.dataset_root(root)
    if not dataset.exists():
        raise MissingRuntimeTree(
            f"No derived chain at {dataset}. Run `python scripts/build_runtime.py` to "
            "derive it from the raw data, or point PAYOFF_RUNTIME at a tree that has "
            "already been built."
        )
    return store.scan(root).filter(pl.col("date") == day)


@lru_cache(maxsize=512)
def minute_slice(day: date, moment: str | datetime) -> pl.DataFrame:
    """Every row of the latest stored minute at or before `moment`.

    One minute of the filled Chain: a row for every strike that has traded by now,
    carrying the last quote and the minute it printed in. This is the as-of view, and it
    is a slice rather than a computation because the fill happened in the build (#67).

    Cached per minute: the store is immutable for the life of the process, so the same
    minute cannot produce two different slices.
    """
    rows = (
        chain_scan(day)
        .filter(pl.col("timestamp_utc") <= _at(moment))
        .filter(pl.col("timestamp_utc") == pl.col("timestamp_utc").max())
        .collect()
    )
    if rows.is_empty():
        raise StrikeNotQuoted(0.0, "--")
    return rows


def strict_slice(moment: str | datetime, day: str | date | None = None) -> pl.DataFrame:
    """Every quote **actually stamped** at that minute, rather than carried into it.

    The counterpart to `snapshot()`, and not a substitute for it. A chain is served
    as-of because a strict reading of it is too thin to trade from; the Forward, the
    Discount Factor and the at-the-money strike are read strictly, because they are
    facts about a minute rather than about a strike's last print.

    `quoted_at == timestamp_utc` is what strict means now the fill is stored: it selects
    exactly the rows that existed before the carry-forward, which is why every figure
    derived from this view is unchanged by #67.
    """
    rows = minute_slice(_on(moment, day), moment)
    return rows.filter(pl.col("quoted_at") == pl.col("timestamp_utc"))


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


def forward_at(
    moment: str | datetime, day: str | date | None = None
) -> forward_maths.ForwardFit:
    """The Forward and Discount Factor this moment implies (#51) - **read, not fitted**.

    The regression ran in the build, once per minute, and its answer is on every row of
    that minute along with the tier that produced it. Reading it back is not a shortcut
    past #51: the number is the engine's own, and `build_runtime.py --check` re-derives
    every day and compares, so a tree written by older code is caught rather than served.

    `pairs` is the one field of the fit the store does not carry, and it is recovered
    rather than invented - it is the size of the both-sided set, which is in the minute.
    Off the **strict** rows, because that is the set the regression actually ran on; the
    filled minute would count strikes whose last print was hours ago.
    """
    rows = strict_slice(moment, day)
    return forward_maths.ForwardFit(
        forward=float(rows["forward"][0]),
        discount=float(rows["discount"][0]),
        T=float(rows["dte_days"][0]) / TRADING_DAYS_PER_YEAR,
        method=str(rows["forward_method"][0]),
        pairs=int(paired_strikes(rows).size),
    )


def expiry_delta(forward: float, strikes: np.ndarray, *, is_call: bool) -> np.ndarray:
    """Delta at `T = 0`, where `black76_greeks` refuses to answer and is right to.

    Gamma divides by a time-scaling that is zero and theta is the change over a session
    that no longer exists, so the core raises there (#26) rather than returning a number
    that looks like an exposure. Delta is the one exposure that survives: the Expiry line
    is the discounted intrinsic, and its slope in the Forward is 1 above the strike and 0
    below it. That is not a limit invented here - it is the derivative of the same
    `black76_price` branch the chart's green line is drawn from.

    Reached on exactly one minute of this dataset, the last bar of Expiry day.
    """
    above = np.asarray(forward > strikes, dtype=float)
    return above if is_call else above - 1.0


@lru_cache(maxsize=256)
def _snapshot(day: date, moment: str | datetime) -> pl.DataFrame:
    """The Chain as-of `moment`: the last known quote for every strike at or before it.

    Every row carries `age_minutes`. On the anchor day the median quote is one minute
    old while the wings reach 153, and presenting the second as live would be dishonest
    rather than merely imprecise.

    Cached per moment. Callers treat the frame as read-only.
    """
    at = _at(moment)
    latest = minute_slice(day, moment).with_columns(
        # Implied volatility is a property of the STRIKE, not of the side. Served as-of,
        # a call and its put can be minutes apart: of the 41 both-sided strikes at the
        # anchor minute only 9 share a minute, and the rest disagree by up to 0.0275. The
        # one that belongs to the strike is the freshest of the two.
        #
        # Freshest of the two that HAS one. A row whose price no volatility reproduces
        # carries null, and a null is not a fresher answer than the other side's number -
        # it is the absence of one. Ranking those rows last is what says so; where both
        # sides are null the strike genuinely has none and stays null.
        pl.col("iv").sort_by(
            pl.when(pl.col("iv").is_null())
            .then(pl.lit(datetime.min, dtype=pl.Datetime("ms")))
            .otherwise(pl.col("quoted_at"))
        ).last().over("strike").alias("strike_iv"),
        (pl.lit(at) - pl.col("quoted_at")).dt.total_minutes().alias("age_minutes"),
    ).sort("strike", "option_type")

    # Delta is **computed**, never read (#53). It is priced at the moment being asked
    # about - this minute's forward, discount and T - and at the strike's one shared
    # volatility, not at whatever minute each side last printed in. A delta is a property
    # of the model now, not of when a print happened to land; pricing the two sides in
    # two different minutes gives a call and a put whose deltas do not even satisfy
    # parity, which is what the source file's own columns do here.
    fit = forward_at(moment, day)
    is_call = (latest["option_type"] == "CE").to_numpy()
    strikes = latest["strike"].to_numpy()
    volatility = latest["strike_iv"].to_numpy()

    # A strike with no volatility has no delta either, and says so rather than being
    # priced at a fabricated one. It is the same nullability `ChainRow.iv` already
    # carries, one field along: both come from a print that no volatility reproduces.
    # At Expiry the gate does not apply - the Expiry line has a slope whether or not
    # anything is implied, which is precisely why nothing is implied there.
    expired = fit.T <= 0.0
    priceable = np.isfinite(volatility) & (volatility > 0.0)

    delta = np.full(latest.height, np.nan)
    for call in (True, False):
        side = (is_call == call) & (True if expired else priceable)
        if not side.any():
            continue
        delta[side] = (
            expiry_delta(fit.forward, strikes[side], is_call=call) if expired
            else black76_greeks(
                fit.forward, strikes[side], fit.T, volatility[side], fit.discount, is_call=call
            )["delta"]
        )
    return latest.with_columns(delta=pl.Series("delta", delta))


def snapshot(moment: str | datetime, day: str | date | None = None) -> pl.DataFrame:
    """The Chain as-of `moment`, on the date the caller named or the moment implies."""
    return _snapshot(_on(moment, day), moment)


def spot_at(moment: str | datetime, day: str | date | None = None) -> float:
    """The NIFTY level at the moment - what the header shows.

    Off the strict minute rather than off the last row of the day up to here, which is
    the same number: Spot is observed once per minute and repeats across every strike in
    it, which is why #64 moves it into a summary artifact of its own.
    """
    return float(strict_slice(moment, day)["spot"][0])


def at_the_money(moment: str | datetime, day: str | date | None = None) -> float:
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
    rows = strict_slice(moment, day)
    paired = paired_strikes(rows)
    candidates = paired if paired.size else np.sort(rows["strike"].unique().to_numpy())
    if not len(candidates):
        raise StrikeNotQuoted(0.0, "--")
    return float(candidates[np.abs(candidates - forward_at(moment, day).forward).argmin()])


def resolve_legs(
    requests: list[LegRequest], moment: str | datetime, day: str | date | None = None
) -> list[Leg]:
    """Turn what the client asked for into Legs the engine can price.

    This is where implied volatility enters the system - **looked up, never accepted
    from the client**. A client that posted a wrong value would get a plausible-looking
    wrong chart that nothing else would catch.

    Entry Premium is the Chain's last traded price unless the client overrode it
    (story 18), which is the one price a trader legitimately supplies.
    """
    quotes = {
        (quote["strike"], quote["option_type"]): quote
        for quote in snapshot(moment, day).iter_rows(named=True)
    }

    legs = []
    for request in requests:
        key = (request.strike, request.option_type)
        if key not in quotes:
            raise StrikeNotQuoted(request.strike, request.option_type)
        quote = quotes[key]

        # A Leg needs a volatility to be priced at, and a strike whose print no
        # volatility reproduces has none - as does every strike in the last minute of
        # Expiry day, where the price stops depending on one. Said plainly here rather
        # than left to surface as a `float(None)` four frames down. #31 owns what a
        # client sees; what matters at this line is that it is not a TypeError.
        if quote["strike_iv"] is None:
            raise ValueError(
                f"{request.strike:.0f} {request.option_type} carries no implied "
                "volatility at this moment, so it cannot be priced"
            )

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


@lru_cache(maxsize=32)
def expiry_label(day: date = ANCHOR_DATE) -> str:
    """The Expiry this date traded, formatted off the **partition key**.

    `expiry=2026-02-10` -> `10FEB26`. It used to be read off an instrument name inside
    the file; now it comes from the path the tree was written under, which is the one
    place a second Expiry would ever announce itself. There is exactly one across all
    twenty-four dates, which is why the header shows text rather than a dropdown - and
    why the manifest (#67) records the pairing anyway, so the day a second series appears
    nothing has to be migrated.
    """
    expiry = chain_scan(day).select(pl.col("expiry").first()).collect().item()
    return f"{expiry.day:02d}{MONTHS[expiry.month - 1]}{expiry.year % 100:02d}"


@lru_cache(maxsize=32)
def moments(day: date = ANCHOR_DATE) -> list[str]:
    """Every minute a client may ask for, in session order.

    **Derived from the data, never from a clock.** 09:15 to 15:30 IST is 376 minutes on
    the anchor and 150 on 7 January; a minute in which nothing quoted has no bar, and
    offering it as a stop on the time control would hand a trader a slider position that
    returns an empty Chain.

    **ISO 8601**, with the `T`, which is also what `as_of_view` echoes back. Both
    spellings parse on the way *in* and were free to differ on the way out - and a client
    that compares the moment on a Chain against the entry it asked for would have found
    them unequal every single time, with nothing to see on screen. One spelling out, and
    it is the one `Date` is specified to parse.
    """
    stamps = (
        chain_scan(day).select("timestamp_utc").unique().sort("timestamp_utc").collect()
    )
    return [stamp.isoformat() for stamp in stamps["timestamp_utc"]]


@lru_cache(maxsize=32)
def strike_bounds(day: date = ANCHOR_DATE) -> tuple[float, float]:
    """The lowest and highest strike quoted anywhere in the session.

    The day's range, not a minute's: a single minute quotes fewer strikes than the day
    does, and an axis that resized as the trader moved through time would make two
    charts of the same Strategy incomparable.
    """
    low, high = (
        chain_scan(day)
        .select(pl.col("strike").min().alias("low"), pl.col("strike").max().alias("high"))
        .collect()
        .row(0)
    )
    return float(low), float(high)


def as_of_view(moment: str | datetime, day: str | date | None = None) -> ChainResponse:
    """The Chain a trader sees: one row per strike, call and put either side.

    Served as-of, because a strict reading of "the Chain at this moment" is nine
    strikes quoting both sides out of the ninety-four in the store - and on some minutes
    of this day, none at all. The last known quote at or before the moment gives 41.
    """
    on = _on(moment, day)
    sides: dict[float, dict[str, ChainQuote]] = {}
    strike_iv: dict[float, float | None] = {}
    for quote in snapshot(moment, on).iter_rows(named=True):
        volatility = quote["strike_iv"]
        strike_iv[float(quote["strike"])] = None if volatility is None else float(volatility)
        side = "call" if quote["option_type"] == "CE" else "put"
        sides.setdefault(float(quote["strike"]), {})[side] = ChainQuote(
            last=float(quote["last"]),
            open_interest=float(quote["open_interest"]),
            volume=float(quote["volume"]),
            delta=None if not np.isfinite(quote["delta"]) else float(quote["delta"]),
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
    fit = forward_at(moment, on)
    return ChainResponse(
        moment=_at(moment).isoformat(),
        spot=spot_at(moment, on),
        expiry=expiry_label(on),
        forward=fit.forward,
        discount=fit.discount,
        forward_method=fit.method,
        rows=rows,
    )

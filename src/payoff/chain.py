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

**And the header no longer opens the Chain at all (#69).** Spot, the Forward, the Discount
Factor and the at-the-money volatility belong to the *minute*, not to the strike, and in
the stored Chain they repeat across every one of that minute's ~196 rows. They are stored
once in a Summary artifact of 375 rows a day, and `summary_scan` is what reads it. So is
`moments()`: one row per minute is one stop per minute, which is exactly the time
control's list. Dragging the time control across a session moves the header 375 times, and
not one of those touches the million-row artifact any more.

The two artifacts describe the same minutes and **cannot be allowed to disagree** about
them, which is why the Summary is reduced from the Chain frame in the build rather than
solved a second time, and why the rules that produce its fields - `STRICT`,
`strike_volatility`, `at_the_money_strike` - live here, in the module that reads them back.

Delta is the exception, and deliberately so: it is **computed on every request** (#53),
because it is a property of the model at the moment being asked about rather than a fact
about a print. It costs one vectorised Black-76 call over the ninety-odd strikes in view.

**Every read takes a date, and may take an Expiry.** Until #67 the store held one date
and this module filtered to it by a constant. Now it holds twenty-four, and the date
comes from the request - either explicitly or off the moment, which already carries one.
`ANCHOR_DATE` survives as the default for the session endpoint, which has no moment to
read one from.

The Expiry is optional and stays optional (#68). Omitted, a read covers every series that
traded that day, which is what a caller who was never offered a choice means. Named, it
covers exactly one. Which pairs exist is not a question for this module - `catalog.py`
answers it off the manifest, and `chain_scan` refuses a pair the manifest does not hold
rather than filtering the store down to nothing and letting the as-of slice report a
strike that was never quoted.

The core never sees a Chain. A strike absent from it raises **here** (#23).
"""

from datetime import date, datetime
from functools import lru_cache

import numpy as np
import polars as pl

from payoff import catalog, store
from payoff import forward as forward_maths
from payoff.models import (
    ChainQuote,
    ChainResponse,
    ChainRow,
    Leg,
    LegRequest,
    SummaryResponse,
)
from payoff.pricing import TRADING_DAYS_PER_YEAR, black76_greeks

ANCHOR_DATE = date(2026, 1, 27)
"""The date served when a caller names none.

Every published figure in `docs/calculations.md` was measured on it, so it is where
`/session` opens when a link names no date: the one day whose numbers a reader can check
against the document. A **default**, not a filter - #67 built the other twenty-three,
`/chain` reaches them, and #68 gives a trader the control that names one.
"""

MONTHS = catalog.MONTHS
"""Spelled out rather than left to `strftime('%b')`, which is locale-dependent: the Expiry
label is asserted as `10FEB26` and a machine set to fr_FR would serve `10FÉVR.26`.

The table itself moved to `catalog` when #68 gave an Expiry label a way *in* as well as
out - a dropdown and a URL both hand one back, and reading it is that module's job. Kept
under this name because it is the one `seed.MONTHS` points at as its opposite number.
"""


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


def _keyed_scan(dataset: str, day: date, expiry: date | None) -> pl.LazyFrame:
    """One dataset's tree, filtered to one date and, optionally, one Expiry.

    Shared by `chain_scan` and `summary_scan` rather than written twice, and that is the
    point rather than a tidiness: the Chain and the Summary are **partitioned
    identically** (#69), so a date that selects one has to select the other. Two spellings
    of this filter is how the two artifacts start describing different minutes.

    Both keys reach the reader as **partition predicates**, so the other twenty-three days
    are skipped before a byte of column data is read.

    `expiry` is optional and **not** because one Expiry exists (#68). Omitted, the plan
    covers every series that traded that day, which is what a caller who has not been
    given a choice means. Named, it covers exactly one - and the day a second series
    appears that is the difference between a Chain and two Chains interleaved, which is
    not something a client could see on screen.

    The pair is checked against the manifest *before* the plan is built, so a date that
    was never derived says so here. Filtering to it would produce an empty frame instead,
    and the first thing to notice used to be the as-of slice, which called it a strike
    that was not quoted. That is a true sentence about the wrong subject.
    """
    root = store.runtime_root()
    folder = store.dataset_root(root, dataset)
    if not folder.exists():
        raise MissingRuntimeTree(
            f"No derived {dataset} at {folder}. Run `python scripts/build_runtime.py` to "
            "derive it from the raw data, or point PAYOFF_RUNTIME at a tree that has "
            "already been built."
        )
    catalog.require(day, expiry)

    plan = store.scan(root, dataset).filter(pl.col("date") == day)
    return plan if expiry is None else plan.filter(pl.col("expiry") == expiry)


@lru_cache(maxsize=32)
def chain_scan(day: date = ANCHOR_DATE, expiry: date | None = None) -> pl.LazyFrame:
    """The lazy plan every **strike-level** read below is composed onto.

    Cached because building the plan globs the tree, not because it holds rows - it holds
    none. Collecting it twice reads the parquet twice, which is the point: the filter
    goes to the reader rather than to a frame already in memory.

    Only what is genuinely per-strike comes through here now (#69). Spot, the Forward, the
    Discount Factor, the at-the-money strike and its volatility are facts about the minute,
    and reading one of them off this plan meant opening the artifact that holds 196 copies
    of it. They come off `summary_scan` instead.
    """
    return _keyed_scan(store.CHAIN, day, expiry)


@lru_cache(maxsize=32)
def summary_scan(day: date = ANCHOR_DATE, expiry: date | None = None) -> pl.LazyFrame:
    """The per-minute plan: **one row a minute**, and never a strike (#69).

    375 rows a day against the Chain's 50,287, holding exactly the figures that belong to
    the minute. Everything the header shows and every stop the time control offers is a
    lookup here, and none of them opens the Chain.

    The same `_keyed_scan` and therefore the same partition predicates as the Chain, which
    is what makes "the same minute" mean the same thing in both.
    """
    return _keyed_scan(store.SUMMARY, day, expiry)


@lru_cache(maxsize=512)
def minute_slice(
    day: date, moment: str | datetime, expiry: date | None = None
) -> pl.DataFrame:
    """Every row of the latest stored minute at or before `moment`.

    One minute of the filled Chain: a row for every strike that has traded by now,
    carrying the last quote and the minute it printed in. This is the as-of view, and it
    is a slice rather than a computation because the fill happened in the build (#67).

    Cached per minute: the store is immutable for the life of the process, so the same
    minute cannot produce two different slices.
    """
    rows = (
        chain_scan(day, expiry)
        .filter(pl.col("timestamp_utc") <= _at(moment))
        .filter(pl.col("timestamp_utc") == pl.col("timestamp_utc").max())
        .collect()
    )
    if rows.is_empty():
        raise StrikeNotQuoted(0.0, "--")
    return rows


@lru_cache(maxsize=512)
def minute_summary(
    day: date, moment: str | datetime, expiry: date | None = None
) -> dict:
    """The one Summary row for the latest stored minute at or before `moment` (#69).

    The whole of the header, in one row of a 375-row artifact. Sliced exactly the way
    `minute_slice` slices the Chain - latest stamp at or before the moment - so the two
    artifacts cannot land on different minutes for one request.

    Cached per minute, for the same reason and with the same guarantee: the store is
    immutable for the life of the process.
    """
    rows = (
        summary_scan(day, expiry)
        .filter(pl.col("timestamp_utc") <= _at(moment))
        .filter(pl.col("timestamp_utc") == pl.col("timestamp_utc").max())
        .collect()
    )
    if rows.is_empty():
        raise StrikeNotQuoted(0.0, "--")
    return rows.row(0, named=True)


def _summary(
    moment: str | datetime,
    day: str | date | None = None,
    expiry: str | date | None = None,
) -> dict:
    """`minute_summary`, addressed the way the wire addresses everything else."""
    return minute_summary(_on(moment, day), moment, catalog.as_expiry(expiry))


STRICT = pl.col("quoted_at") == pl.col("timestamp_utc")
"""The rows **actually stamped** at their minute, rather than carried into it.

The counterpart to the as-of view, and not a substitute for it. A chain is served as-of
because a strict reading of it is too thin to trade from; the Forward, the Discount
Factor and the at-the-money strike are derived strictly, because they are facts about a
minute rather than about a strike's last print - a stale bar in the parity regression
lands in the Discount Factor directly.

`quoted_at == timestamp_utc` is what strict means now the fill is stored (#67): it
selects exactly the rows that existed before the carry-forward. Spelled here, once, and
exported because `scripts/build_runtime.py` reduces the Chain to the Summary through it
(#69) - a second spelling in the writer is how the Summary starts describing a minute
that the Chain does not.
"""


def strike_volatility(*over: str) -> pl.Expr:
    """One implied volatility per strike, from its **freshest** quote (#28).

    A property of the strike and not of the side: served as-of, a call and its put can be
    minutes apart and imply volatilities up to 0.0275 apart, and publishing both would
    contradict the model that produced them.

    Freshest of the two **that has one**. A row whose price no volatility reproduces
    carries null, and a null is not a fresher answer than the other side's number - it is
    the absence of one. Ranking those rows last is what says so; where both sides are null
    the strike genuinely has none and stays null.

    `over` is the grouping, and it is a parameter because the same rule is applied at two
    scales: the reader has one minute in hand and groups by strike alone, while the build
    has a whole day and groups by minute and strike (#69). One definition either way -
    the at-the-money volatility the header reads must be the volatility the Chain reports
    at that strike, and two implementations of "freshest" is exactly how it would not be.
    """
    return (
        pl.col("iv")
        .sort_by(
            pl.when(pl.col("iv").is_null())
            .then(pl.lit(datetime.min, dtype=pl.Datetime("ms")))
            .otherwise(pl.col("quoted_at"))
        )
        .last()
        .over(*over)
    )


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
    moment: str | datetime,
    day: str | date | None = None,
    expiry: str | date | None = None,
) -> forward_maths.ForwardFit:
    """The Forward and Discount Factor this moment implies (#51) - **read, not fitted**.

    The regression ran in the build, once per minute, and its answer is on the Summary
    row for that minute along with the tier that produced it. Reading it back is not a
    shortcut past #51: the number is the engine's own, and `build_runtime.py --check`
    re-derives every day and compares both artifacts, so a tree written by older code is
    caught rather than served.

    **Off the Summary rather than off the Chain (#69).** All five fields are facts about
    the minute, so every one of them repeated across the minute's 196 Chain rows; a fit is
    now one row of a 375-row artifact. `pairs` is stored with the rest for the same reason
    it used to be recounted here - it is the size of the both-sided **strict** set, which
    is a property of the minute the regression ran on and not of the filled view, where a
    strike's last print may be hours old.
    """
    row = _summary(moment, day, expiry)
    return forward_maths.ForwardFit(
        forward=float(row["forward"]),
        discount=float(row["discount"]),
        T=float(row["dte_days"]) / TRADING_DAYS_PER_YEAR,
        method=str(row["forward_method"]),
        pairs=int(row["pairs"]),
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
def _snapshot(
    day: date, moment: str | datetime, expiry: date | None = None
) -> pl.DataFrame:
    """The Chain as-of `moment`: the last known quote for every strike at or before it.

    Every row carries `age_minutes`. On the anchor day the median quote is one minute
    old while the wings reach 153, and presenting the second as live would be dishonest
    rather than merely imprecise.

    Cached per moment. Callers treat the frame as read-only.
    """
    at = _at(moment)
    latest = minute_slice(day, moment, expiry).with_columns(
        # Implied volatility is a property of the STRIKE, not of the side. Served as-of,
        # a call and its put can be minutes apart: of the 41 both-sided strikes at the
        # anchor minute only 9 share a minute, and the rest disagree by up to 0.0275. The
        # rule is `strike_volatility`, and it is spelled there rather than here because
        # the build applies the same one to fill the Summary's `atm_iv` (#69). One minute
        # in hand, so the grouping is the strike alone.
        strike_volatility("strike").alias("strike_iv"),
        (pl.lit(at) - pl.col("quoted_at")).dt.total_minutes().alias("age_minutes"),
    ).sort("strike", "option_type")

    # Delta is **computed**, never read (#53). It is priced at the moment being asked
    # about - this minute's forward, discount and T - and at the strike's one shared
    # volatility, not at whatever minute each side last printed in. A delta is a property
    # of the model now, not of when a print happened to land; pricing the two sides in
    # two different minutes gives a call and a put whose deltas do not even satisfy
    # parity, which is what the source file's own columns do here.
    fit = forward_at(moment, day, expiry)
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


def snapshot(
    moment: str | datetime,
    day: str | date | None = None,
    expiry: str | date | None = None,
) -> pl.DataFrame:
    """The Chain as-of `moment`, on the date the caller named or the moment implies."""
    return _snapshot(_on(moment, day), moment, catalog.as_expiry(expiry))


def spot_at(
    moment: str | datetime,
    day: str | date | None = None,
    expiry: str | date | None = None,
) -> float:
    """The NIFTY level at the moment - what the header shows.

    Off the Summary (#69). Spot is observed once per minute and repeated across every
    strike of that minute in the Chain, so reading it there meant opening the artifact
    that holds 196 copies of it to take one.
    """
    return float(_summary(moment, day, expiry)["spot"])


def at_the_money_strike(rows: pl.DataFrame, forward: float) -> float:
    """The quoted strike nearest the **Forward** (#51), out of one strict minute.

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

    Takes a frame rather than a moment, because since #69 the caller is the **build**: the
    answer is stored on the Summary row and `at_the_money` reads it back. Kept here, in
    the module that owns what the money means, so that the rule has one home whichever
    side of the store is applying it.
    """
    paired = paired_strikes(rows)
    candidates = paired if paired.size else np.sort(rows["strike"].unique().to_numpy())
    if not len(candidates):
        raise StrikeNotQuoted(0.0, "--")
    return float(candidates[np.abs(candidates - forward).argmin()])


def at_the_money(
    moment: str | datetime,
    day: str | date | None = None,
    expiry: str | date | None = None,
) -> float:
    """The at-the-money strike at this moment, read off the Summary (#69).

    A fact about the minute, chosen once by the build with `at_the_money_strike` and
    stored. What used to be a strict slice of the Chain, a set intersection and a fit is
    one field of one row.
    """
    return float(_summary(moment, day, expiry)["atm_strike"])


def at_the_money_volatility(
    moment: str | datetime,
    day: str | date | None = None,
    expiry: str | date | None = None,
) -> float | None:
    """The at-the-money strike's implied volatility - the header's fourth figure (#69).

    The strike's one volatility, by `strike_volatility`'s rule, which is the same number
    `ChainRow.iv` carries for that strike at that minute. That is the assertion the split
    lives or dies on: two artifacts describing one minute must not be able to disagree
    about it.

    Nullable, and for the reason `ChainRow.iv` is: a print no volatility reproduces has
    none, and every strike in the last minute of Expiry day is such a print. `None` is the
    honest answer and a fabricated number is not.
    """
    value = _summary(moment, day, expiry)["atm_iv"]
    return None if value is None else float(value)


def resolve_legs(
    requests: list[LegRequest], moment: str | datetime, day: str | date | None = None
) -> list[Leg]:
    """Turn what the client asked for into Legs the engine can price.

    This is where implied volatility enters the system - **looked up, never accepted
    from the client**. A client that posted a wrong value would get a plausible-looking
    wrong chart that nothing else would catch.

    Entry Premium is the Chain's last traded price unless the client overrode it
    (story 18), which is the one price a trader legitimately supplies.

    **Each Leg is looked up in its own Expiry** (#71), because that is the series it names
    and 25200 CE is a different contract in each. One snapshot per distinct Expiry, built
    once and reused, so the ordinary Strategy still reads one minute of one partition -
    and a Strategy naming two would read both correctly rather than silently reading one
    of them twice. `strategy.sole_expiry` is what stops such a Strategy reaching here; it
    is not this function's job to assume it did.
    """
    snapshots: dict[str, dict[tuple[float, str], dict]] = {}

    def quotes_in(expiry: str) -> dict[tuple[float, str], dict]:
        if expiry not in snapshots:
            snapshots[expiry] = {
                (quote["strike"], quote["option_type"]): quote
                for quote in snapshot(moment, day, expiry).iter_rows(named=True)
            }
        return snapshots[expiry]

    legs = []
    for request in requests:
        key = (request.strike, request.option_type)
        quotes = quotes_in(request.expiry)
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
                expiry=request.expiry,
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
def expiry_label(day: date = ANCHOR_DATE, expiry: date | None = None) -> str:
    """The Expiry this date traded, formatted off the **partition key**.

    `expiry=2026-02-10` -> `10FEB26`. It used to be read off an instrument name inside
    the file; now it comes from the path the tree was written under, which is the one
    place a second Expiry would ever announce itself.

    Read off the **manifest** rather than off `expiry` directly, so the label is one the
    tree actually holds and not the one the caller believed. The manifest is the index
    over the partitions and the build writes it last off the tree itself, so it carries
    the same guarantee a partition key does - and it is a twenty-four-row file rather than
    the Chain, which is what lets `/summary` answer without opening a strike (#69).

    Where no Expiry was named the answer is the day's first, which is what "the Expiry of
    this date" can mean when the caller was not given a choice; #68's dropdown always
    names one, and `catalog.expiries` is what it lists.
    """
    catalog.require(day, expiry)
    return catalog.label(expiry if expiry is not None else catalog.expiries(day)[0])


def expiry_at(
    moment: str | datetime,
    day: str | date | None = None,
    expiry: str | date | None = None,
) -> str:
    """`expiry_label`, addressed the way the wire addresses everything else.

    Exists for the Preset endpoint (#71): a Preset now builds Legs that carry an Expiry,
    so it has to be told which series it is building in - and where a caller named none,
    the answer is the one the Chain would have served for that minute, not a constant.
    """
    return expiry_label(_on(moment, day), catalog.as_expiry(expiry))


@lru_cache(maxsize=32)
def moments(day: date = ANCHOR_DATE, expiry: date | None = None) -> list[str]:
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

    **Off the Summary (#69).** The list of minutes *is* the Summary's index - one row per
    minute is exactly one stop per minute - so the time control's stops are read from a
    375-row artifact rather than distilled out of a 50,287-row one by a distinct-values
    pass over every strike of every minute.
    """
    stamps = (
        summary_scan(day, expiry)
        .select("timestamp_utc")
        .unique()
        .sort("timestamp_utc")
        .collect()
    )
    return [stamp.isoformat() for stamp in stamps["timestamp_utc"]]


@lru_cache(maxsize=32)
def strike_bounds(
    day: date = ANCHOR_DATE, expiry: date | None = None
) -> tuple[float, float]:
    """The lowest and highest strike quoted anywhere in the session.

    The day's range, not a minute's: a single minute quotes fewer strikes than the day
    does, and an axis that resized as the trader moved through time would make two
    charts of the same Strategy incomparable.
    """
    low, high = (
        chain_scan(day, expiry)
        .select(pl.col("strike").min().alias("low"), pl.col("strike").max().alias("high"))
        .collect()
        .row(0)
    )
    return float(low), float(high)


def summary_view(
    moment: str | datetime,
    day: str | date | None = None,
    expiry: str | date | None = None,
) -> SummaryResponse:
    """The header, at one minute, without opening the Chain (#69).

    Spot, the Forward, the Discount Factor and the at-the-money volatility, plus the
    strike that last one belongs to and the tier that produced the Forward. Every one of
    them is a field of a single Summary row, so the request that moving the time control
    makes is a lookup rather than a slice of the largest artifact in the tree.

    `moment` echoes back what was asked for rather than the minute that answered it,
    exactly as `as_of_view` does - a client comparing the moment it sent against the one
    it got must find them equal on both endpoints or on neither.
    """
    on = _on(moment, day)
    series = catalog.as_expiry(expiry)
    fit = forward_at(moment, on, series)

    return SummaryResponse(
        moment=_at(moment).isoformat(),
        date=on.isoformat(),
        expiry=expiry_label(on, series),
        spot=spot_at(moment, on, series),
        forward=fit.forward,
        discount=fit.discount,
        forward_method=fit.method,
        atm_strike=at_the_money(moment, on, series),
        atm_iv=at_the_money_volatility(moment, on, series),
    )


def as_of_view(
    moment: str | datetime,
    day: str | date | None = None,
    expiry: str | date | None = None,
) -> ChainResponse:
    """The Chain a trader sees: one row per strike, call and put either side.

    Served as-of, because a strict reading of "the Chain at this moment" is nine
    strikes quoting both sides out of the ninety-four in the store - and on some minutes
    of this day, none at all. The last known quote at or before the moment gives 41.
    """
    on = _on(moment, day)
    series = catalog.as_expiry(expiry)
    sides: dict[float, dict[str, ChainQuote]] = {}
    strike_iv: dict[float, float | None] = {}
    for quote in snapshot(moment, on, series).iter_rows(named=True):
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
    fit = forward_at(moment, on, series)
    return ChainResponse(
        moment=_at(moment).isoformat(),
        spot=spot_at(moment, on, series),
        expiry=expiry_label(on, series),
        forward=fit.forward,
        discount=fit.discount,
        forward_method=fit.method,
        rows=rows,
    )

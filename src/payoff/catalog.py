"""What exists: which trading dates were stored, and which Expiries each of them traded.

Read off the **manifest** (#67) - the one small unpartitioned artifact the build writes
last and unconditionally - and never by walking the tree. Twenty-four rows, read whole.
That is what lets the two dropdowns above the Chain (#68) open without touching a data
file: a client asks `/session` once and is handed both lists, and neither list is a
property of a generated fixture that could drift from what the engine would serve.

**Both directions come out of the same rows.** Which Expiries a date traded is a filter
on `date`; which dates an Expiry traded on is a filter on `expiry`. Keeping the pairing
*as pairs* is what makes it many-to-many without a second copy of the tree, and it is why
a second series appearing is a build re-run rather than a migration. Only one Expiry
exists today, and nothing below is allowed to assume that: a lookup that returns one
element is not the same code as a lookup that cannot return two.

Nothing here opens a partition. `chain.py` serves rows; this answers what rows there are,
and a client asks in that order because it cannot name a date until it has been told
which dates exist.
"""

from datetime import date
from functools import lru_cache

import polars as pl

from payoff import store

MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
"""Spelled out rather than left to `strftime('%b')` / `strptime('%b')`, both of which are
locale-dependent: the Expiry label is asserted as `10FEB26` and a machine set to fr_FR
would serve `10FÉVR.26` and fail to read it back. `chain.MONTHS` is this same table -
`seed.MONTHS` is a third copy, going from a ticker rather than from a label.

The table lives here because this is the module that has to read a label as well as write
one: an Expiry arrives from a dropdown and a URL as the text a trader saw, and it has to
become the Date the tree is keyed by before anything can be filtered on it.
"""


class NotStored(LookupError):
    """A date or an Expiry the build never wrote.

    A `LookupError` rather than a `ValueError` because the request is well-formed and the
    thing it names is simply not there - which is the difference between a 404 and a 422.
    `api.py` turns it into the former; **#31 owns what the body looks like.**
    """


class UnknownDate(NotStored):
    """A trading date with no partition under it.

    Named because the alternative is what this replaces: filtering the store to a date
    that was never built yields an empty frame, and the first thing downstream to notice
    was the as-of slice, which reported `0 -- is not quoted at or before this moment`.
    That sentence is true and tells a caller nothing - not that the date is the problem,
    not which dates would have worked.
    """

    def __init__(self, day: date, stored: tuple[date, ...]) -> None:
        self.day = day
        self.stored = stored
        span = f"{stored[0]} to {stored[-1]}" if stored else "nothing at all"
        super().__init__(
            f"{day} was not built. The store holds {len(stored)} trading dates, {span}; "
            "run `python scripts/build_runtime.py` to widen it."
        )


class UnknownExpiry(NotStored):
    """An Expiry that did not trade on the date it was asked for.

    The pairing failure #68 exists to make unreachable from the interface - and which
    therefore has to be answerable over the wire anyway, because a link is hand-editable
    and a dropdown is not the only way in.
    """

    def __init__(self, expiry: date, day: date, traded: tuple[date, ...]) -> None:
        self.expiry = expiry
        self.day = day
        self.traded = traded
        offered = ", ".join(label(one) for one in traded) or "no Expiry at all"
        super().__init__(f"{label(expiry)} did not trade on {day}, which traded {offered}")


class UnreadableExpiry(ValueError):
    """Text that is not an Expiry label. A 422 rather than a 404: nothing was looked up."""

    def __init__(self, text: str) -> None:
        super().__init__(f'cannot read "{text}" as an Expiry; the form is 10FEB26')


class MissingManifest(RuntimeError):
    """A chain tree with no manifest beside it, which means a build stopped half way.

    The manifest is written **last and unconditionally** precisely so that this cannot
    happen to a finished build - so reaching this is a statement about the tree, not
    about the reader, and re-running the build is the fix. Distinct from
    `chain.MissingRuntimeTree`, which is no tree at all rather than a partial one.
    """


def label(expiry: date) -> str:
    """`2026-02-10` -> `10FEB26`: the Expiry as a trader reads it, and as `/chain` says it.

    One spelling on the wire. The dropdown renders this, the URL carries it, `/chain`
    accepts it and `ChainResponse.expiry` echoes it, so a client can compare what it
    asked for against what it got without a conversion in the middle.
    """
    return f"{expiry.day:02d}{MONTHS[expiry.month - 1]}{expiry.year % 100:02d}"


def parse_label(text: str) -> date:
    """`10FEB26` -> `2026-02-10`. The inverse of `label`, and it refuses anything else.

    Deliberately not liberal. Accepting an ISO date here as well would mean the same
    Expiry had two spellings in the URL, so two links describing one view would not
    compare equal - and the session's list, which is what a client picks from, is only
    ever spelled one way.
    """
    body = text.strip().upper()
    if len(body) != 7 or body[2:5] not in MONTHS:
        raise UnreadableExpiry(text)
    try:
        return date(2000 + int(body[5:7]), MONTHS.index(body[2:5]) + 1, int(body[:2]))
    except ValueError as error:
        raise UnreadableExpiry(text) from error


def as_expiry(value: str | date | None) -> date | None:
    """An Expiry from whatever a caller held: a label, a Date already, or nothing."""
    if value is None or isinstance(value, date):
        return value
    return parse_label(str(value))


@lru_cache(maxsize=1)
def pairs() -> pl.DataFrame:
    """The manifest: every (date, Expiry) the build stored, ascending.

    Cached for the life of the process because the store is immutable for the life of the
    process - the same argument `chain.chain_scan` is cached on. One file of twenty-four
    rows, so the cache is about not paying a parquet open per dropdown rather than about
    memory.

    Collected rather than returned lazy, unlike everything in `chain.py`: there is nothing
    here for a predicate to push down to, and every caller wants all of it.
    """
    root = store.runtime_root()
    folder = store.dataset_root(root, store.MANIFEST)
    if not folder.exists():
        raise MissingManifest(
            f"No manifest at {folder}, though a chain tree exists. The build writes it "
            "last, so this is a build that stopped part way through: re-run "
            "`python scripts/build_runtime.py`."
        )
    return (
        store.scan(root, store.MANIFEST)
        .select("date", "expiry")
        .unique()
        .sort("date", "expiry")
        .collect()
    )


def dates() -> tuple[date, ...]:
    """Every trading date in the store, ascending. What the date dropdown lists."""
    return tuple(pairs()["date"].unique().sort().to_list())


def expiries(day: date) -> tuple[date, ...]:
    """The Expiries that traded on one date, ascending. What the Expiry dropdown lists.

    Empty for a date that was never built, which is a question about the date and is
    answered as one by `require`.
    """
    return tuple(pairs().filter(pl.col("date") == day)["expiry"].sort().to_list())


def require(day: date, expiry: date | None = None) -> None:
    """Refuse a pair the store does not hold, naming what it does.

    The **strict** direction, for a caller who asked for something specific: `/chain` is
    asked for one date and one Expiry and must never quietly serve another, because a
    Chain that is not the one that was requested is indistinguishable on screen from one
    that is.
    """
    stored = dates()
    if day not in stored:
        raise UnknownDate(day, stored)
    traded = expiries(day)
    if expiry is not None and expiry not in traded:
        raise UnknownExpiry(expiry, day, traded)


def resolve(
    day: str | date | None, expiry: str | date | None, *, default: date
) -> tuple[date, date]:
    """A pair that is certainly stored, out of whatever a link happened to carry.

    The **forgiving** direction, and the acceptance criterion it answers is #68's:
    *"selecting a date whose Expiry set differs from the current selection resolves to a
    valid pair rather than an empty Chain"*. A trader changes the date and the Expiry in
    the URL is one interaction behind; what comes back is the pair the Chain will
    actually serve, and the client renders that rather than what it asked for.

    **Date wins over Expiry**, because that is the order the two dropdowns are picked in
    (#64): a day first, then what that day offered. Resolving the other way would move a
    trader off the date they just clicked.

    Forgiving *here* and strict in `require` is the difference between the two endpoints
    rather than an inconsistency. `/session` is how a client learns what exists, so it
    has to answer; answering with a valid pair is the only answer that is any use, and a
    session describing a day the rest of the API does not serve is worse than none.
    """
    stored = dates()
    if not stored:
        raise MissingManifest("The manifest is empty: no trading date has been built.")

    on = _as_date(day)
    if on not in stored:
        on = default if default in stored else stored[0]

    traded = expiries(on)
    series = _as_date(expiry) if isinstance(expiry, date) else _as_label(expiry)
    return on, series if series in traded else traded[0]


def _as_date(value: str | date | None) -> date | None:
    """An ISO date, or `None` for anything that is not one.

    Unreadable text falls back rather than raising, because this is only reached from
    `resolve`, whose whole job is to answer. A hand-truncated link is the likeliest way
    to hold one, and showing a real day beats an error page.
    """
    if value is None or isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _as_label(value: str | None) -> date | None:
    """An Expiry label, or `None` for anything that is not one. Forgiving, as above."""
    if value is None:
        return None
    try:
        return parse_label(str(value))
    except UnreadableExpiry:
        return None

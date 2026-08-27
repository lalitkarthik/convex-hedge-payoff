"""Derive every trading day and write it as Hive-partitioned parquet.

This is where the 1.4 s a day lives. The engine derives the forward and discount by
put-call parity (#51) and the volatility by Newton (#52) - 376 fits and 18,994 solves on
the anchor - and a process that redoes that at every start redoes it for nothing, because
the day is immutable. So it happens here, once, and the API only reads.

    Data/options.parquet + Data/index.parquet   the raw bars
      -> seed.seed(day)                         the IST/UTC join, per date
      -> derive.fits / solved_volatility        forward, discount, volatility
      -> carry_forward()                        every minute for every strike
      -> Data/runtime/chain_v1/asset=.../date=.../expiry=.../part-0.parquet
      -> Data/runtime/payoff_v1/part-0.parquet            corner points, unpartitioned
      -> Data/runtime/manifest_v1/part-0.parquet          written last, from the tree

**Which direction the Oracle flows matters.** Nothing here, and nothing under `src/`,
opens `Data/greeks.parquet`; it is a test fixture and feeds no served byte. What lands in
the runtime tree is the engine's own answer. CONTEXT.md:138.

Three properties of the written files are decisions rather than accidents.

**The carry-forward is applied here, not per request (#67).** Only strikes that actually
traded in a minute have a bar, so the Chain a trader expects has to be filled from each
strike's last known quote - and doing that at request time repeats it 376 times as they
drag the time control. Filling it here turns the request into a row slice. 568,736 quoted
bars become 1,062,024 filled rows, a factor of 1.9 rather than the 3 the strike count
suggests, because the early dates are thin.

**A strike is not carried forward before its first trade of the day.** There is nothing
to carry, and a fabricated row is worse than an absent one.

**Each file is sorted by timestamp then strike, in row groups of about four thousand
rows** - roughly twenty minutes of a session. Column-store statistics are the only
mechanism that lets a filter skip data, and an unsorted file gives the lazy scan nothing
to skip: the laziness would be decoration.

**The Payoff artifact is one file for the whole dataset, not one per day (#70).**
`max(F - K, 0)` depends on the strike and the type and on nothing else, so partitioning
it by date would write twenty-four identical copies of the same 588 rows.

Usage:  python scripts/build_runtime.py [root]
        python scripts/build_runtime.py [root] --dates=2026-01-27,2026-02-10
        python scripts/build_runtime.py [root] --check     reconcile without writing
"""

import sys
from datetime import date
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from payoff import derive, seed, store, strategy  # noqa: E402  - after the path is set

ASSET = "NIFTY"
DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "Data" / "runtime"
"""The runtime root, holding one versioned tree per dataset - not a dataset root itself."""

ROW_GROUP_ROWS = 4_000
"""About twenty minutes of a session, and the unit a filter can skip.

Parquet keeps min/max statistics per row group, so a predicate on `timestamp_utc` can
discard a group without decompressing it - but only because the file is **sorted** by
that column first. Smaller groups skip more and compress worse; four thousand rows is
where the day's ninety-odd strikes give a group a couple of distinct minutes rather than
a couple of hundred."""

#: `greeks.parquet`'s own types, so a comparison against it is field for field. The
#: timestamp is milliseconds and the strings are large - both differ from what Polars
#: would choose unprompted, which is the whole reason this mapping is written out.
SCHEMA = {
    "timestamp_utc": pl.Datetime("ms"),
    "quoted_at": pl.Datetime("ms"),
    "strike": pl.Float64,
    "option_type": pl.String,
    "last": pl.Float64,
    "volume": pl.Int64,
    "open_interest": pl.Int64,
    "spot": pl.Float64,
    "dte_days": pl.Float64,
    "forward": pl.Float64,
    "discount": pl.Float64,
    "forward_method": pl.String,
    "iv": pl.Float64,
}
"""The columns as they are written.

Two have **no counterpart** in `greeks.parquet` and are stored anyway.

`forward_method` because #51 exists to make an assumed forward distinguishable from a
measured one - on 60 of the anchor's 376 minutes the regression could not be trusted -
and dropping that label to match a file format would undo the ticket.

`quoted_at` because the carry-forward moved into the build (#67). `timestamp_utc` is now
the minute a row is *served at* and `quoted_at` the minute its bar actually printed in;
the two are equal only on a row that traded. Their difference is the quote age a trader
reads, and it is the one thing a filled row cannot be honest without. It is also what
makes the strict view still strict: `quoted_at == timestamp_utc` recovers exactly the
rows that were there before the fill.

The five Greeks are **not** stored. Delta is computed on every request (#53) at the
moment being asked about and at the strike's one shared volatility, which a per-row
stored Greek could not be - it would have to pick one side's volatility, and the two
disagree by up to 0.0275 when the sides are minutes apart. A stored column that
disagreed with the served one would be worse than an absent column.
"""

MANIFEST_SCHEMA = {
    "asset": pl.String,
    "date": pl.Date,
    "expiry": pl.Date,
    "forward_min": pl.Float64,
    "forward_max": pl.Float64,
}
"""What the manifest records: which Expiries pair with which dates (#67), and the two
bounds of the shared Forward domain (#70).

The tree answers one direction of the pairing already - a date's directory contains its
expiries - but not the other, and walking twenty-four directories to answer "which dates
did this series trade on" is a directory listing pretending to be a query.

The two bounds repeat on every row, which is a fact about one dataset written once per
pairing. They are read back off the Payoff artifact rather than recomputed here, so the
number the manifest publishes is the number the stored corners actually sit on - the one
arrangement in which writer and reader cannot end up disagreeing.
"""

PAYOFF_SCHEMA = {
    "strike": pl.Float64,
    "option_type": pl.String,
    "corner": pl.Int8,
    "forward": pl.Float64,
    "payoff": pl.Float64,
}
"""The Payoff artifact: three corner points per (strike, side) (#70).

`corner` is 0, 1, 2 - the low end of the domain, the strike, the high end - and it is
stored rather than inferred from the ordering because "three corners per Leg" is the
claim this representation rests on, and a claim that is only true of the sort order is
one nothing can check. It also survives a reader that sorts by something else.

`payoff` is premium-blind, in CONTEXT.md's sense: `max(F - K, 0)` for a call and
`max(K - F, 0)` for a put. Subtracting the Entry Premium is what turns it into P&L, and
that is the caller's job, because the Entry Premium is a property of the trade rather
than of the contract.
"""

FAR_TAIL = 2.0
"""How far above the highest strike the domain's upper bound sits.

Twice the highest strike, which is what `strategy._kinks` used before the domain moved
into the manifest. The number itself does not matter to any published figure - beyond
the highest strike every Payoff is a straight line, so the far corner only has to be far
enough out that the line is unambiguous. What matters is that it is **one** number for
the whole dataset rather than one per Leg.

The lower bound is 0.0 and is not a parameter: the Forward cannot fall below zero
(CONTEXT.md), which is why only the right-hand tail can ever be Unbounded and why a long
put's maximum profit is its strike less what was paid for it.
"""


def quoted_frame(day: date, expiry: date) -> pl.DataFrame:
    """One day as it was quoted: a row per strike, per side, per minute that traded.

    Everything derived - the forward, the discount, the method, the volatility - and
    nothing filled. `runtime_frame` fills it.
    """
    quotes = derive.solved_chain(day)
    fits = derive.fits(day)

    return pl.DataFrame(
        {
            "timestamp_utc": quotes.ts.to_numpy(),
            "quoted_at": quotes.ts.to_numpy(),
            "strike": quotes.strike.to_numpy(float),
            "option_type": quotes.option_type.to_numpy(),
            "last": quotes["last"].to_numpy(float),
            "volume": quotes.volume.to_numpy(),
            "open_interest": quotes.open_interest.to_numpy(),
            "spot": quotes.spot.to_numpy(float),
            "dte_days": quotes.dte_days.to_numpy(float),
            "forward": [fits[stamp].forward for stamp in quotes.ts],
            "discount": [fits[stamp].discount for stamp in quotes.ts],
            "forward_method": [fits[stamp].method for stamp in quotes.ts],
            "iv": quotes.iv.to_numpy(float),
        }
    ).select(
        [pl.col(name).cast(dtype) for name, dtype in SCHEMA.items()]
    ).with_columns(
        # A price no volatility reproduces has no honest answer, and ADR-0001 bans NaN
        # from the wire - so it is stored as **null**, which is what the nullable
        # `ChainRow.iv` exists to carry. A NaN survives parquet, reaches pydantic and
        # fails validation there, on the one minute of the dataset where every row has
        # one: the last bar of Expiry day.
        pl.col("iv").fill_nan(None)
    )


#: The columns that belong to a **quote** and are therefore carried forward with it.
#: Everything else belongs to the minute the row is served at and is taken from there.
CARRIED = ("quoted_at", "last", "volume", "open_interest", "iv")

#: The columns that are facts about a minute rather than about a strike: they repeat
#: across every row of the minute and are joined on, never filled.
PER_MINUTE = ("spot", "dte_days", "forward", "discount", "forward_method")


def carry_forward(quoted: pl.DataFrame) -> pl.DataFrame:
    """Every minute for every strike, with the last known quote carried across.

    The fill is done on `quoted_at` alone and the quote is then joined back on it, rather
    than forward-filling the value columns directly. That is not a stylistic preference:
    `iv` is legitimately null on a row whose price no volatility reproduces, and a
    forward-fill of the values would quietly replace that null with the previous minute's
    volatility - inventing a number for the one case the nullable column exists to
    report.

    A strike's row appears from the minute of its first trade and not before. Before it
    the fill has nothing to carry, so `quoted_at` is still null there and the row is
    dropped - which is why the factor is 1.9 rather than the strike count.
    """
    minutes = quoted.select("timestamp_utc", *PER_MINUTE).unique("timestamp_utc")
    keys = quoted.select("strike", "option_type").unique()
    quotes = quoted.select("strike", "option_type", *CARRIED)
    traded = quoted.select("strike", "option_type", "quoted_at").with_columns(
        timestamp_utc=pl.col("quoted_at")
    )

    return (
        minutes.select("timestamp_utc")
        .join(keys, how="cross")
        .join(traded, on=["timestamp_utc", "strike", "option_type"], how="left")
        .sort("timestamp_utc")
        .with_columns(pl.col("quoted_at").forward_fill().over("strike", "option_type"))
        .drop_nulls("quoted_at")
        .join(quotes, on=["strike", "option_type", "quoted_at"], how="left")
        .join(minutes, on="timestamp_utc", how="left")
    )


def runtime_frame(day: date = derive.ANCHOR, expiry: date | None = None) -> pl.DataFrame:
    """The day, derived and filled, in the order and types `SCHEMA` names.

    Sorted by timestamp then strike, which is what makes the row-group statistics worth
    keeping: a predicate on a minute discards whole groups, and within a group a
    predicate on a strike discards pages.
    """
    if expiry is None:
        expiry = seed.expiries_on(day)[0]

    filled = carry_forward(quoted_frame(day, expiry))
    return filled.select(
        [pl.col(name).cast(dtype) for name, dtype in SCHEMA.items()]
    ).sort("timestamp_utc", "strike", "option_type")


def write_day(root: Path | str, day: date, expiry: date) -> Path:
    """Write one (asset, date, expiry) partition. Returns its directory.

    Any other parquet already in the partition is removed first. A rebuild that renamed
    its output would otherwise leave the old file beside the new one and the scan would
    read both - a duplicate day that no assertion about the writer would ever see.
    """
    frame = runtime_frame(day, expiry)

    part = store.partition_path(root, asset=ASSET, date=str(day), expiry=str(expiry))
    part.mkdir(parents=True, exist_ok=True)
    target = part / "part-0.parquet"
    for stale in part.glob("*.parquet"):
        if stale != target:
            stale.unlink()

    frame.write_parquet(target, row_group_size=ROW_GROUP_ROWS)
    return part


def _unpartitioned(root: Path | str, dataset: str, frame: pl.DataFrame) -> Path:
    """Write one small whole-dataset file, replacing whatever was there.

    The same replace-rather-than-add discipline `write_day` uses, and for the same
    reason: a second parquet left beside the first is read by the scan as extra rows.
    """
    root_dir = store.dataset_root(root, dataset)
    root_dir.mkdir(parents=True, exist_ok=True)
    target = root_dir / "part-0.parquet"
    for stale in root_dir.glob("*.parquet"):
        if stale != target:
            stale.unlink()

    frame.write_parquet(target)
    return target


def stored_keys(root: Path | str) -> set[tuple[float, str]]:
    """Every (strike, side) the Payoff artifact already covers, or nothing if it has none.

    Read so that `write_payoff` **extends** rather than replaces. A strike that appeared
    once is a strike a saved Strategy may still name, and dropping it because today's
    build was narrower would take the Expiry line away from a chart that had one.
    """
    if not store.dataset_root(root, store.PAYOFF).exists():
        return set()
    rows = store.scan(root, store.PAYOFF).select("strike", "option_type").unique().collect()
    return {(float(strike), str(side)) for strike, side in rows.rows()}


def chain_keys(root: Path | str) -> set[tuple[float, str]]:
    """Every strike in the stored Chain, crossed with **both** sides.

    Crossed rather than taken as the pairs that traded, because the Payoff of a put at a
    strike that has so far quoted only calls is not unknown - it is `max(K - F, 0)`, and
    it is the same function whether or not anybody has traded it yet. Two of the ninety-
    eight strikes in this dataset quoted one side only, and a trader who picks the other
    side of one of them is asking an ordinary question.
    """
    if not store.dataset_root(root).exists():
        return set()
    strikes = store.scan(root).select("strike").unique().collect()["strike"]
    return {(float(strike), side) for strike in strikes for side in ("CE", "PE")}


def payoff_frame(keys: set[tuple[float, str]]) -> pl.DataFrame:
    """Three corner points for every (strike, side), on one shared Forward domain.

    The domain is a property of the whole set of keys and never of one Leg: the upper
    bound is `FAR_TAIL` times the **highest strike in the dataset**, not that times the
    Leg's own strike. Corners on a per-Leg domain are what makes a Strategy's Legs sum at
    points that are not the same point, and the sum is wrong without ever looking wrong.

    The value at each corner is `strategy.intrinsic_value`, which is the one definition
    of a Payoff in this codebase. Writing `max(F - K, 0)` out again here would be a second
    implementation of the thing the store exists to make there be one of.
    """
    ordered = sorted(keys)
    high = FAR_TAIL * max(strike for strike, _ in ordered)

    rows = []
    for strike, option_type in ordered:
        for corner, forward in enumerate((0.0, strike, high)):
            value = strategy.intrinsic_value(forward, strike, is_call=option_type == "CE")
            rows.append((strike, option_type, corner, forward, float(value)))

    return pl.DataFrame(rows, schema=PAYOFF_SCHEMA, orient="row").sort(
        "strike", "option_type", "corner"
    )


def write_payoff(root: Path | str, extra: tuple[tuple[float, str], ...] = ()) -> Path:
    """Write the one unpartitioned Payoff artifact. Returns the file.

    `extra` names (strike, side) pairs that are not in the Chain yet. **Adding a strike is
    this call and nothing else** - no day is re-derived, no partition is rewritten, and
    the twenty-four chain files are not so much as opened. Which is the point: the Payoff
    of a contract has nothing to do with any day, so widening the set of contracts must
    not cost a rebuild of the days.
    """
    return _unpartitioned(
        root, store.PAYOFF, payoff_frame(chain_keys(root) | stored_keys(root) | set(extra))
    )


def forward_domain(root: Path | str) -> tuple[float, float]:
    """The two bounds the stored corners actually sit on, read off the artifact.

    Read back rather than recomputed, so that the manifest cannot publish a domain the
    Payoff artifact was not written on. Recomputing it would be one line shorter and
    would be wrong the first time the two calls saw different inputs.
    """
    bounds = (
        store.scan(root, store.PAYOFF)
        .select(low=pl.col("forward").min(), high=pl.col("forward").max())
        .collect()
    )
    return float(bounds["low"][0]), float(bounds["high"][0])


def write_manifest(root: Path | str) -> Path:
    """Record the date/Expiry pairing and the Forward domain, read off the tree itself.

    **The build's last step, and unconditional.** Read off the tree rather than off the
    list of dates the build was asked for, so it describes what is actually there; and
    rewritten every time rather than only when the pairing changed, so a manifest from a
    wider build cannot survive a narrower one and go on advertising a day that is no
    longer stored. A dropdown built on a stale manifest offers a date that returns
    nothing, and it fails at the point a trader clicks.

    The Forward domain rides along for the same reason and with the same timing: the
    reader interpolates between corners it did not write, so the bounds it interpolates
    over have to be the bounds they were written on (#70).
    """
    low, high = forward_domain(root)
    pairs = (
        store.scan(root)
        .select("asset", "date", "expiry")
        .unique()
        .sort("asset", "date", "expiry")
        .with_columns(forward_min=pl.lit(low), forward_max=pl.lit(high))
        .collect()
        .select([pl.col(name).cast(dtype) for name, dtype in MANIFEST_SCHEMA.items()])
    )

    return _unpartitioned(root, store.MANIFEST, pairs)


def check(root: Path | str = DEFAULT_ROOT, dates: tuple[date, ...] | None = None) -> int:
    """Compare what is stored against what the engine derives now. Returns an exit code.

    The store exists so the API never derives, which means nothing in production ever
    re-checks these numbers. A tree written by last month's code serves answers no test
    has seen, confidently and silently. This is what CI runs to catch that.
    """
    failures = 0
    for day in dates or seed.trading_dates():
        for expiry in seed.expiries_on(day):
            fresh = runtime_frame(day, expiry)
            stored = (
                store.scan(root)
                .filter(pl.col("date") == day, pl.col("expiry") == expiry)
                .select(fresh.columns)
                .sort("timestamp_utc", "strike", "option_type")
                .collect()
            )
            if stored.equals(fresh):
                print(f"{day}  {stored.height:,} rows agree with the engine")
                continue

            failures += 1
            print(f"{day}  MISMATCH: stored {stored.height:,} against {fresh.height:,} derived")
            for column in fresh.columns:
                if stored.height == fresh.height and not stored[column].equals(fresh[column]):
                    print(f"    {column} differs")
    return 1 if failures else 0


def main(root: Path | str = DEFAULT_ROOT, dates: tuple[date, ...] | None = None) -> Path:
    """Derive the dates and write them under `root`. Returns the runtime root.

    `dates` defaults to every trading date in the dataset. The test suite passes a subset
    - see `tests/conftest.py` for why - and that is the whole reason this is a parameter.

    The order is days, then the Payoff artifact, then the manifest. The Payoff artifact
    has to see the days to know which strikes exist, and the manifest has to see the
    Payoff artifact to publish the domain its corners were written on - which is also why
    the manifest stays last and unconditional.
    """
    written = 0
    for day in dates or seed.trading_dates():
        for expiry in seed.expiries_on(day):
            part = write_day(root, day, expiry)
            rows = pl.scan_parquet(part / "part-0.parquet").select(pl.len()).collect().item()
            written += rows
            print(f"{day}  {rows:>7,} filled rows -> {part.relative_to(root)}")

    payoff = write_payoff(root)
    corners = pl.scan_parquet(payoff).select(pl.len()).collect().item()
    print(f"{corners:>7,} corner points -> {payoff.relative_to(root)}")

    manifest = write_manifest(root)
    low, high = forward_domain(root)
    print(f"{written:,} rows written; forward domain {low:,.0f} to {high:,.0f}")
    print(f"manifest -> {manifest.relative_to(root)}")
    return Path(root)


if __name__ == "__main__":
    args = sys.argv[1:]
    where = [arg for arg in args if not arg.startswith("--")]
    asked = next((arg for arg in args if arg.startswith("--dates=")), None)
    chosen = (
        tuple(date.fromisoformat(part) for part in asked.removeprefix("--dates=").split(","))
        if asked else None
    )
    if "--check" in args:
        raise SystemExit(check(*(where or [DEFAULT_ROOT]), dates=chosen))
    main(*(where or [DEFAULT_ROOT]), dates=chosen)

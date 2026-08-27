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

Usage:  python scripts/build_runtime.py [root]
        python scripts/build_runtime.py [root] --dates=2026-01-27,2026-02-10
        python scripts/build_runtime.py [root] --check     reconcile without writing
"""

import sys
from datetime import date
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from payoff import derive, seed, store  # noqa: E402  - after the path is set

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

MANIFEST_SCHEMA = {"asset": pl.String, "date": pl.Date, "expiry": pl.Date}
"""What the manifest records: which Expiries pair with which dates (#67).

The tree answers one direction of that already - a date's directory contains its
expiries - but not the other, and walking twenty-four directories to answer "which dates
did this series trade on" is a directory listing pretending to be a query.
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


def write_manifest(root: Path | str) -> Path:
    """Record which Expiries pair with which dates, read back off the tree itself.

    **The build's last step, and unconditional.** Read off the tree rather than off the
    list of dates the build was asked for, so it describes what is actually there; and
    rewritten every time rather than only when the pairing changed, so a manifest from a
    wider build cannot survive a narrower one and go on advertising a day that is no
    longer stored. A dropdown built on a stale manifest offers a date that returns
    nothing, and it fails at the point a trader clicks.
    """
    pairs = (
        store.scan(root)
        .select("asset", "date", "expiry")
        .unique()
        .sort("asset", "date", "expiry")
        .collect()
        .select([pl.col(name).cast(dtype) for name, dtype in MANIFEST_SCHEMA.items()])
    )

    root_dir = store.dataset_root(root, store.MANIFEST)
    root_dir.mkdir(parents=True, exist_ok=True)
    target = root_dir / "part-0.parquet"
    for stale in root_dir.glob("*.parquet"):
        if stale != target:
            stale.unlink()

    pairs.write_parquet(target)
    return target


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
    """
    written = 0
    for day in dates or seed.trading_dates():
        for expiry in seed.expiries_on(day):
            part = write_day(root, day, expiry)
            rows = pl.scan_parquet(part / "part-0.parquet").select(pl.len()).collect().item()
            written += rows
            print(f"{day}  {rows:>7,} filled rows -> {part.relative_to(root)}")

    manifest = write_manifest(root)
    print(f"{written:,} rows written; manifest -> {manifest.relative_to(root)}")
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

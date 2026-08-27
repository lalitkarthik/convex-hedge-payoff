"""Derive one trading day and write it as Hive-partitioned parquet.

This is where the 1.4 s lives. The engine derives the forward and discount by put-call
parity (#51) and the volatility by Newton (#52) - 376 fits and 18,994 solves - and a
process that redoes that at every start redoes it for nothing, because the day is
immutable. So it happens here, once, and the API only reads.

    Data/sample/chain_2026-01-27.parquet          the committed seed
      -> derive.load_chain()                      drops forward, discount, iv
      -> derive.forward_at / solved_volatility    derives them back
      -> Data/runtime/chain_v1/asset=.../date=.../expiry=.../part-0.parquet

**Which direction the Oracle flows matters.** This script reads the committed sample and
`derive.load_chain()` drops the graded columns before anything here can see them, so what
lands in the runtime tree is the engine's own answer. Nothing downstream reads
`Data/greeks.parquet`; it stays a test fixture. CONTEXT.md:138.

The written columns follow `Data/greeks.parquet`'s own names and Arrow types, so the two
can be compared field for field - `tests/test_store.py` does exactly that. Three
differences, all deliberate:

  * `volume`, `open_interest` and `spot` are **added**. That file has none of them and
    `ChainQuote` and `ChainResponse` serve all three.
  * `vanna`, `volga` and `charm` are **omitted**. We derive five Greeks, not eight.
  * `asset`, `date` and `expiry` live in the **path**, not in the file. That is what Hive
    partitioning is, and Polars reads them back as columns anyway. `store` spells that
    path, version and all; nothing here decides its shape.

Usage:  python scripts/build_runtime.py [root]
        python scripts/build_runtime.py --check      reconcile without writing
"""

import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from payoff import derive, store  # noqa: E402  - after the path is set

ASSET = "NIFTY"
DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "Data" / "runtime"
"""The runtime root, holding one versioned tree per dataset - not a dataset root itself."""

#: `greeks.parquet`'s own types, so a comparison against it is field for field. The
#: timestamp is milliseconds and the strings are large - both differ from what Polars
#: would choose unprompted, which is the whole reason this mapping is written out.
SCHEMA = {
    "timestamp_utc": pl.Datetime("ms"),
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

`forward_method` is the one with **no counterpart** in `greeks.parquet`, and it is stored
anyway. #51 exists to make an assumed forward distinguishable from a measured one - on 60
of this day's 376 minutes the regression could not be trusted - and dropping that label to
match a file format would undo the ticket.

The five Greeks join this list with #53. They are absent rather than null: a null column
that looks derived is the ambiguity ADR-0001's NaN ban exists to prevent.
"""


def runtime_frame() -> pl.DataFrame:
    """The day, derived, in the order and types `SCHEMA` names."""
    quotes = derive.solved_chain()
    fits = {stamp: derive.forward_at(stamp) for stamp in quotes.ts.unique()}

    frame = pl.DataFrame(
        {
            "timestamp_utc": quotes.ts.to_numpy(),
            "strike": quotes.strike.to_numpy(float),
            "option_type": quotes.option_type.to_numpy(),
            "last": quotes["last"].to_numpy(float),
            "volume": quotes.Volume.to_numpy(),
            "open_interest": quotes.OpenInterest.to_numpy(),
            "spot": quotes.spot.to_numpy(float),
            "dte_days": quotes.dte_days.to_numpy(float),
            "forward": [fits[stamp].forward for stamp in quotes.ts],
            "discount": [fits[stamp].discount for stamp in quotes.ts],
            "forward_method": [fits[stamp].method for stamp in quotes.ts],
            "iv": quotes.iv.to_numpy(float),
        }
    )
    return frame.select(
        [pl.col(name).cast(dtype) for name, dtype in SCHEMA.items()]
    ).sort("timestamp_utc", "strike", "option_type")


def expiry_date() -> str:
    """The expiry as an ISO date, for the partition key.

    The seed names it '10FEB26' on the Ticker; a path key wants something sortable, and
    Polars parses `expiry=2026-02-10` back as a Date rather than a string.
    `chain.expiry_label()` formats it back to '10FEB26' for the header.
    """
    label = derive.expiry_label()
    return str(pl.Series([label]).str.to_date("%d%b%y").item())


def check(root: Path | str = DEFAULT_ROOT) -> int:
    """Compare what is stored against what the engine derives now. Returns an exit code.

    The store exists so the API never derives, which means nothing in production ever
    re-checks these numbers. A tree written by last month's code serves answers no test
    has seen, confidently and silently. This is what CI runs to catch that.
    """
    fresh = runtime_frame()
    stored = store.scan(root).select(fresh.columns).sort(
        "timestamp_utc", "strike", "option_type"
    ).collect()

    if stored.equals(fresh):
        print(f"{stored.height:,} rows agree with the engine")
        return 0

    print(f"MISMATCH: stored {stored.height:,} rows against {fresh.height:,} derived")
    for column in fresh.columns:
        if stored.height == fresh.height and not stored[column].equals(fresh[column]):
            print(f"  {column} differs")
    return 1


def main(root: Path | str = DEFAULT_ROOT) -> Path:
    """Derive the day and write it under `root`. Returns the partition directory."""
    frame = runtime_frame()
    date = str(frame["timestamp_utc"].dt.date().min())

    part = store.partition_path(root, asset=ASSET, date=date, expiry=expiry_date())
    part.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(part / "part-0.parquet")

    minutes = frame.unique("timestamp_utc").get_column("forward_method").value_counts()
    print(f"{frame.height:,} rows, {frame['timestamp_utc'].n_unique()} minutes -> {part}")
    for method, count in sorted(minutes.rows()):
        print(f"  {method:<22} {count:>3} minutes")
    return part


if __name__ == "__main__":
    where = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    if "--check" in sys.argv:
        raise SystemExit(check(*where))
    main(*where)

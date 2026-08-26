"""The runtime store: Hive-partitioned parquet, scanned lazily.

The engine derives every number it serves (#51, #52, #53) and that costs 1.4 s on the
sample day. The store is where the derived day is kept so the cost is paid once, by a
job, rather than on every process start - #23 story 48's "one derived data file loaded
at boot", with the file in S3 and partitioned.

**The Oracle never enters the store.** `Data/*.parquet` stays committed as a test
fixture and is read by `scripts/build_runtime.py` on the way in, never by the engine on
the way out. That is what `chain.load_chain()` dropping the graded columns already
guarantees, and the store inherits it by construction.

Tested against a tree built in `tmp_path`: no bucket, no credentials, no network. The
S3 half is one download away from here and is exercised by `build_runtime.py --check`.
"""

import sys
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq
import pytest

from payoff import store

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_runtime  # noqa: E402  - scripts/ is not a package

DATA = Path(__file__).resolve().parents[1] / "Data"
SAMPLE = DATA / "sample" / "chain_2026-01-27.parquet"
GREEKS = DATA / "greeks.parquet"

UNDERLYING = "NIFTY"
EXPIRY = "2026-02-10"
DATE = "2026-01-27"


@pytest.fixture(scope="module")
def tree(tmp_path_factory) -> Path:
    """A one-partition Hive tree, laid out the way `build_runtime.py` lays one out."""
    root = tmp_path_factory.mktemp("runtime")
    part = root / f"underlying={UNDERLYING}" / f"expiry={EXPIRY}" / f"date={DATE}"
    part.mkdir(parents=True)
    pl.read_parquet(SAMPLE).select(
        "ts", "strike", "option_type", "last", "dte_days", "spot"
    ).write_parquet(part / "part-0.parquet")
    return root


def test_the_partition_keys_come_back_as_columns(tree):
    """Hive partitioning puts `underlying`, `expiry` and `date` in the **path**, not in
    the file - so they cost nothing to store and a filter on one skips whole files
    before a byte of column data is read.

    Asserted because it is the entire reason for the layout. If these were absent the
    tree would be an ordinary directory of parquet and every query would read all of it.
    """
    scanned = store.scan(tree)

    assert isinstance(scanned, pl.LazyFrame), "lazy: nothing is read until it is collected"

    schema = scanned.collect_schema()
    for key in ("underlying", "expiry", "date"):
        assert key in schema.names()

    # Polars types the values it parses off the path. `expiry` arriving as a Date rather
    # than the string in the directory name is what `chain.expiry_label()` has to format.
    assert schema["underlying"] == pl.String
    assert schema["expiry"] == pl.Date
    assert schema["date"] == pl.Date


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Path:
    """The real thing: `build_runtime.main()` run against the committed sample."""
    root = tmp_path_factory.mktemp("built")
    build_runtime.main(root)
    return root


def test_the_written_file_carries_the_oracle_files_own_column_types(built):
    """#52's plan: store the day "exactly in the format given in greeks.parquet".

    Compared at the Arrow level rather than through Polars, because that is where the
    claim actually lives - `timestamp[ms]` against `timestamp[us]` and `large_string`
    against `string` are the differences a Polars-side comparison would hide.

    Only the **shared** columns are compared, and the two sets differ deliberately at
    both ends. `greeks.parquet` has no `volume`, `open_interest` or `spot`, all three of
    which `ChainQuote` and `ChainResponse` serve. We derive five Greeks and it carries
    eight, so `vanna`, `volga` and `charm` are absent here - a column we cannot fill is
    not part of our format.
    """
    written = next(built.rglob("*.parquet"))
    ours = {field.name: field.type for field in pq.ParquetFile(written).schema_arrow}
    oracle = {field.name: field.type for field in pq.ParquetFile(GREEKS).schema_arrow}

    shared = sorted(set(ours) & set(oracle))
    assert shared, "the format claim is empty if the two files share no column"
    for name in shared:
        assert ours[name] == oracle[name], f"{name}: {ours[name]} against {oracle[name]}"

    assert {"volume", "open_interest", "spot"} <= set(ours), "what the chain table serves"
    assert not {"vanna", "volga", "charm"} & set(ours), "not derived, so not stored"
    assert not {"underlying", "expiry", "date"} & set(ours), "these live in the path"


def test_the_partition_holds_the_whole_day(built):
    """One file per (underlying, expiry, date), and the day is 23,581 rows.

    The count is the sample's own, asserted in `test_data_contract.py`. If the writer
    ever drops rows - a join that half-matches, a filter that fires - this is what says
    so, and it says it before anything downstream renders a chain with holes in it.
    """
    part = store.partition_path(built, underlying=UNDERLYING, expiry=EXPIRY, date=DATE)
    assert part.is_dir(), "the Hive layout the reader expects"

    frame = store.scan(built).collect()
    assert frame.height == 23_581
    assert frame["underlying"].unique().to_list() == [UNDERLYING]


def test_the_stored_day_is_what_the_engine_derives_right_now(built):
    """The mitigation for the risk this whole design creates.

    Production reads the store; the tests grade the **engine**. Nothing structurally
    stops the two disagreeing - a bucket written by last month's code serves numbers no
    test has ever seen, and it serves them confidently.

    So: re-derive from the committed sample and compare. Exact equality, not a tolerance
    - both sides are the same float64 through the same code, and a difference of any size
    means the file was written by something other than what is running.

    Deliberately **not** graded against `Data/greeks.parquet` here. That the engine
    reproduces the Oracle is `test_forward.py`'s and `test_implied_vol.py`'s claim, and
    those two files are the only places those columns are opened.
    """
    stored = store.scan(built).sort("timestamp_utc", "strike", "option_type").collect()
    fresh = build_runtime.runtime_frame()

    for column in build_runtime.SCHEMA:
        assert stored[column].to_list() == fresh[column].to_list(), column


def test_every_minute_carries_the_method_that_produced_its_forward(built):
    """#51's ladder, counted at the far end of the pipeline.

    316 minutes were measured by regression; 50 fell back to single-strike parity and 10
    to spot alone. The split is asserted here as well as in `test_forward.py` because a
    writer that silently dropped `forward_method` would leave every stored forward
    looking equally trustworthy - which is the one thing #51 exists to prevent.
    """
    minutes = (
        store.scan(built)
        .unique("timestamp_utc")
        .group_by("forward_method")
        .len()
        .collect()
    )
    assert dict(minutes.rows()) == {
        "parity_fit": 316,
        "single_strike_parity": 50,
        "spot": 10,
    }

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

import re
import sys
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq
import pytest

from payoff import chain, store

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_runtime  # noqa: E402  - scripts/ is not a package

DATA = Path(__file__).resolve().parents[1] / "Data"
SAMPLE = DATA / "sample" / "chain_2026-01-27.parquet"
GREEKS = DATA / "greeks.parquet"

ASSET = "NIFTY"
EXPIRY = "2026-02-10"
DATE = "2026-01-27"

LAYOUT = f"chain_v1/asset={ASSET}/date={DATE}/expiry={EXPIRY}"
"""The tree, spelled out by hand rather than by `store.partition_path`.

Written twice on purpose. Every other seam in this project grades what comes back over
HTTP, and this one cannot: a tree keyed `expiry` above `date`, or keyed `underlying`
instead of `asset`, holds the same rows in the same order and serves byte-identical
responses. There is no assertion above this line that could see the difference. So the
agreement between reader and writer is checked here against a literal, and calling the
function that produces the path would only assert that it equals itself.
"""


@pytest.fixture(scope="module")
def tree(tmp_path_factory) -> Path:
    """A one-partition Hive tree, laid out the way `build_runtime.py` lays one out."""
    root = tmp_path_factory.mktemp("runtime")
    part = root / LAYOUT
    part.mkdir(parents=True)
    pl.read_parquet(SAMPLE).select(
        "ts", "strike", "option_type", "last", "dte_days", "spot"
    ).write_parquet(part / "part-0.parquet")
    return root


def test_the_partition_keys_come_back_as_columns(tree):
    """Hive partitioning puts `asset`, `date` and `expiry` in the **path**, not in the
    file - so they cost nothing to store and a filter on one skips whole files before a
    byte of column data is read.

    Asserted because it is the entire reason for the layout. If these were absent the
    tree would be an ordinary directory of parquet and every query would read all of it.
    """
    scanned = store.scan(tree)

    assert isinstance(scanned, pl.LazyFrame), "lazy: nothing is read until it is collected"

    schema = scanned.collect_schema()
    for key in ("asset", "date", "expiry"):
        assert key in schema.names()

    # Polars types the values it parses off the path. `expiry` arriving as a Date rather
    # than the string in the directory name is what `chain.expiry_label()` has to format.
    assert schema["asset"] == pl.String
    assert schema["date"] == pl.Date
    assert schema["expiry"] == pl.Date


def test_a_new_derivation_version_is_a_new_root_rather_than_a_migration(tree, monkeypatch):
    """#65: the derivation version is part of the dataset root's name.

    Which is only worth something if it actually selects. The delta and gamma convention
    changed once already and invalidated every stored Greek; the point of the version is
    that re-deriving under `v2` leaves `v1` in place, so rolling back is a pointer change
    rather than a migration. So: bump it, and the tree that was written under the old one
    must become invisible rather than be read as if it were current.
    """
    assert store.dataset_root(tree).name == f"{store.CHAIN}_{store.DERIVATION_VERSION}"
    assert re.fullmatch(r"v\d+", store.DERIVATION_VERSION), "a version, not a label"
    assert store.scan(tree).collect().height, "readable under the version it was written by"

    monkeypatch.setattr(store, "DERIVATION_VERSION", "v99")
    assert not store.dataset_root(tree).exists()
    with pytest.raises(Exception, match="(?i)expanded paths were empty"):
        store.scan(tree).collect()


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
    assert not {"asset", "expiry", "date"} & set(ours), "these live in the path"


def test_the_writer_lays_the_tree_out_in_the_agreed_order(built):
    """#65's whole point, and the one claim no HTTP test can make.

    Not "a parquet file exists somewhere underneath": the exact relative path, every
    directory name and their order, against a literal. Swap `date` and `expiry`, or go
    back to `underlying`, and every assertion in this file except this one still passes -
    the rows are identical, the schema is identical, the served bytes are identical. The
    breakage surfaces later, in whatever reads the tree by a path it spelled itself.
    """
    written = sorted(path.relative_to(built).as_posix() for path in built.rglob("*.parquet"))
    assert written == [f"{LAYOUT}/part-0.parquet"]

    # And the one function allowed to spell that path agrees with the literal above.
    part = store.partition_path(built, asset=ASSET, date=DATE, expiry=EXPIRY)
    assert part == built / LAYOUT
    assert part.is_dir(), "the Hive layout the reader expects"


def test_the_partition_holds_the_whole_day(built):
    """One file per (asset, date, expiry), and the day is 23,581 rows.

    The count is the sample's own, asserted in `test_data_contract.py`. If the writer
    ever drops rows - a join that half-matches, a filter that fires - this is what says
    so, and it says it before anything downstream renders a chain with holes in it.
    """
    frame = store.scan(built).collect()
    assert frame.height == 23_581
    assert frame["asset"].unique().to_list() == [ASSET]


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


def test_a_missing_tree_stops_the_reader_rather_than_re_deriving(tmp_path, monkeypatch):
    """#66's other half: the serving path reads the store, and *only* the store.

    `Data/runtime/` is gitignored - it is derived, not authored - so the tree is genuinely
    absent in a fresh clone, and the tempting fix is a fallback that re-derives from the
    committed sample when it cannot be found. That fallback would be worse than the bug it
    hides: it puts the 1.4 s back into the first request, which is the whole cost #64
    exists to remove, and it makes a misconfigured `PAYOFF_RUNTIME` look like a working
    deployment serving slightly slower.

    So the reader raises, and the message names the command that fixes it. Asserted here
    because no HTTP test can be: a fallback would serve byte-identical responses, which is
    exactly the property that would let it survive review.
    """
    monkeypatch.setattr(store, "runtime_root", lambda: tmp_path)
    chain.chain_scan.cache_clear()
    try:
        with pytest.raises(chain.MissingRuntimeTree, match="build_runtime"):
            chain.chain_scan()
    finally:
        chain.chain_scan.cache_clear()

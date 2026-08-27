"""The runtime store: Hive-partitioned parquet, scanned lazily.

The engine derives every number it serves (#51, #52, #53) and that costs 1.4 s on the
sample day. The store is where the derived day is kept so the cost is paid once, by a
job, rather than on every process start - #23 story 48's "one derived data file loaded
at boot", with the file in S3 and partitioned.

**The Oracle never enters the store.** `Data/*.parquet` stays committed as a test
fixture and is read by `scripts/build_runtime.py` on the way in, never by the engine on
the way out. Since #67 nothing under `src/` or `scripts/` opens it at all, which the
store inherits by construction and `tests/test_seed.py` asserts directly.

Tested against a tree built in `tmp_path`: no bucket, no credentials, no network. The
S3 half is one download away from here and is exercised by `build_runtime.py --check`.
"""

import re
import sys
from datetime import date
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
    """The real thing: `build_runtime.main()` run against the raw data.

    One date. #67 taught the build to derive all twenty-four and that costs 47.7 s; every
    claim below is about **a** partition and how it is written, not about how many there
    are, so building a second one would buy nothing and cost a coffee. That all
    twenty-four build is `tests/test_seed.py`'s claim, made without deriving.
    """
    root = tmp_path_factory.mktemp("built")
    build_runtime.main(root, (date.fromisoformat(DATE),))
    return root


@pytest.fixture(scope="module")
def part(built) -> Path:
    """The one chain partition under `built`.

    Named rather than reached for with `next(rglob(...))`, which since #67 can hand back
    the manifest instead - it is a parquet file under the same root and it sorts first.
    """
    return built / LAYOUT / "part-0.parquet"


def test_the_written_file_carries_the_oracle_files_own_column_types(built, part):
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
    ours = {field.name: field.type for field in pq.ParquetFile(part).schema_arrow}
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
    assert written == [f"{LAYOUT}/part-0.parquet", "manifest_v1/part-0.parquet"]

    # And the one function allowed to spell that path agrees with the literal above.
    partition = store.partition_path(built, asset=ASSET, date=DATE, expiry=EXPIRY)
    assert partition == built / LAYOUT
    assert partition.is_dir(), "the Hive layout the reader expects"


def test_the_partition_holds_the_whole_day(built):
    """One file per (asset, date, expiry): 23,581 quoted bars, filled to 50,287 rows.

    The first count is the sample's own, asserted in `test_data_contract.py`, and it is
    what says the writer never drops a row - a join that half-matches or a filter that
    fires would show up here before anything downstream rendered a chain with holes in
    it. Recovering it from the stored file needs `quoted_at == timestamp_utc`, because
    since #67 the file also holds every minute a strike **did not** trade in, with its
    last quote carried across.

    The second count is what the carry-forward costs on this day, and it is a fact about
    liquidity rather than about arithmetic: 94 strikes on both sides over 376 minutes
    would be 70,688 if every strike had traded from the open, and the gap is the strikes
    that had not opened yet.
    """
    frame = store.scan(built).collect()
    assert frame.height == 50_287, "every minute, for every strike, once it has traded"
    assert frame.filter(
        pl.col("quoted_at") == pl.col("timestamp_utc")
    ).height == 23_581, "the quoted bars, unchanged by the fill"
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


def test_the_file_is_sorted_by_timestamp_then_strike_in_bounded_row_groups(part):
    """#67. Sorting is what makes the lazy read a read rather than a decoration.

    Column-store statistics are the only mechanism that lets a filter skip data: parquet
    keeps a min and a max per row group, and a predicate outside that range discards the
    group without decompressing it. In an unsorted file every group's `timestamp_utc`
    range spans the whole session, so a filter on one minute skips nothing and the lazy
    scan reads all 50,287 rows to return two hundred.

    Asserted on the file itself rather than through Polars, because a frame read back
    would be sorted whatever the file did. Three claims: the rows are ordered, the groups
    are bounded, and - the one that actually matters - the groups **do not overlap** in
    time, which is the property a filter exploits and the one that sorting buys.
    """
    parquet = pq.ParquetFile(part)
    assert parquet.metadata.num_row_groups > 1, "one group is one thing to skip: itself"

    spans = []
    for group in range(parquet.metadata.num_row_groups):
        meta = parquet.metadata.row_group(group)
        assert meta.num_rows <= build_runtime.ROW_GROUP_ROWS

        column = next(
            meta.column(at) for at in range(meta.num_columns)
            if meta.column(at).path_in_schema == "timestamp_utc"
        )
        spans.append((column.statistics.min, column.statistics.max))

    assert spans == sorted(spans), "groups in time order"
    for earlier, later in zip(spans, spans[1:]):
        assert earlier[1] <= later[0], "a later group never reaches back into an earlier one"

    frame = pl.read_parquet(part)
    assert frame.equals(frame.sort("timestamp_utc", "strike", "option_type"))


def test_the_manifest_says_which_expiries_pair_with_which_dates(built):
    """#67. The tree answers one direction of the pairing; this answers the other.

    A date's directory lists its expiries, so "what did 27 January offer" is a directory
    listing. "Which dates did the 10 Feb series trade on" is twenty-four of them, and a
    dropdown that has to walk the tree to populate itself is not lazy, it is slow.
    """
    manifest = store.scan(built, store.MANIFEST).collect()

    assert manifest.columns == list(build_runtime.MANIFEST_SCHEMA)
    assert manifest.rows() == [(ASSET, date.fromisoformat(DATE), date.fromisoformat(EXPIRY))]
    assert manifest.schema["date"] == pl.Date, "sortable, not a string"


def test_the_manifest_is_written_last_and_cannot_outlive_what_it_describes(tmp_path):
    """#67: "written as the build's last step, unconditionally".

    Both halves are load-bearing and neither is obvious.

    **Last**, because a manifest written first describes the tree the build intended
    rather than the tree it produced, and a build that dies halfway leaves the two
    disagreeing with nothing to notice.

    **Unconditionally, and read off the tree**, because otherwise a narrower rebuild
    inherits a wider build's manifest and goes on advertising a date that is no longer
    stored. That failure surfaces at the point a trader clicks a dropdown entry and gets
    nothing back, which is three screens away from the cause.
    """
    wide = (date(2026, 1, 7), date(2026, 1, 27))
    build_runtime.main(tmp_path, wide)
    assert store.scan(tmp_path, store.MANIFEST).collect().height == 2

    # A rebuild of one date over that tree. The other partition is still on disk - this
    # is not a test that the build cleans up - so the manifest must describe two, and it
    # must have been rewritten rather than merely left alone.
    build_runtime.main(tmp_path, (date(2026, 1, 7),))
    listed = store.scan(tmp_path, store.MANIFEST).collect()["date"].to_list()
    assert listed == list(wide), "read off the tree, not off the list of dates asked for"


def test_a_rebuild_over_an_existing_tree_is_idempotent(tmp_path):
    """#67. A build that has already run must be safe to run again.

    The failure this guards is not corruption, it is **accumulation**: a writer that
    named its output after the run, or appended rather than replaced, would leave two
    files in one partition and the scan would read both. Every row would appear twice,
    every count would double, and the chain would still render - each strike simply
    quoted twice at every minute.

    So the tree is compared byte for byte, and the row count with it.
    """
    day = (date(2026, 1, 7),)
    build_runtime.main(tmp_path, day)
    before = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in sorted(tmp_path.rglob("*.parquet"))
    }

    build_runtime.main(tmp_path, day)
    after = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in sorted(tmp_path.rglob("*.parquet"))
    }

    assert list(after) == list(before), "no file gained, no file lost"
    assert after == before, "and none of them changed"
    assert store.scan(tmp_path).collect().height == 1_744, "the sparse day, counted once"


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

"""Where the derived day is kept, and how it is read.

The engine derives everything it serves - the forward and discount by put-call parity
(#51), the volatility by Newton (#52), the Greeks from Black-76 (#53). On the sample day
that costs **1.4 s**, and a process that pays it at every start pays it for nothing: the
day is immutable. So a job derives once and writes here, and the API only reads.

That is #23 story 48 - *"the Chain served from one derived data file loaded at boot, so
that the deployment is a static artefact rather than a database to operate"* - with two
qualifications. The artefact lives in S3 rather than in the repository, and it is
**Hive-partitioned**:

    chain_v1/asset=NIFTY/date=2026-01-27/expiry=2026-02-10/part-0.parquet

The partition keys are in the **path**, so they cost nothing to store, a filter on one
skips whole files before a byte of column data is read, and a second trading day or a
second expiry is a new prefix rather than a migration.

Two details of that path are decisions rather than accidents (#65). **`asset`, and date
above expiry**: the key names and their order follow the reference system's own derived
tree, and date sits above expiry because that is the order a trader picks in - a day
first, then what that day offered. **`_v1`**: the derivation version is part of the
dataset root, so changing the pricing model writes a new root and rolling back is a
pointer change rather than a migration. The delta and gamma convention has already
changed once and invalidated every stored Greek, so that is not hypothetical.

**The Oracle is not here.** `Data/greeks.parquet` and its siblings stay committed as test
fixtures; `scripts/build_runtime.py` reads them on the way in, and nothing reads them on
the way out. CONTEXT.md:138 - the engine that reads the Oracle to produce an answer has
lost the point of the project.
"""

import os
from functools import lru_cache
from pathlib import Path

import polars as pl

PART_GLOB = "**/*.parquet"

CHAIN = "chain"
"""The Chain: one row per minute, per strike, per side, with the carry-forward already
applied (#67). Partitioned by asset, date and expiry. #64 adds a summary and a payoff."""

SUMMARY = "summary"
"""The Summary: **one row per minute**, holding only what belongs to the minute (#69).

Spot, the Forward, the Discount Factor and the at-the-money volatility are facts about a
minute rather than about a strike. In the Chain they repeat across every strike of that
minute - about 196 rows on a dense day - and reading one of them means opening a file
that holds 1,062,024 of them. Here they are stored once: 375 rows a day, 8,735 across the
dataset, small enough to hold in memory for a whole session.

The header shows those four figures and the time control changes them 375 times as a
trader drags across a session. Every one of those was a touch of the large artifact and
is now a lookup in a small one.

**Partitioned identically to the Chain** - `asset`, then `date`, then `expiry` - so the
same filter selects the same partition, and a date that exists in one exists in the other.
A different layout here would mean the two artifacts describing one minute could be
selected differently, which is the one failure a split like this must not introduce.

It is **derived from the Chain frame the build has just written**, never solved a second
time. Two artifacts describing one minute that can disagree are worse than one artifact;
reducing the rows that are about to be stored is the only arrangement in which they
cannot.
"""

PAYOFF = "payoff"
"""The Payoff of a Leg at Expiry, as corner points (#70).

**Unpartitioned, and one file for the whole dataset.** `max(F - K, 0)` depends on the
strike and the type and on nothing else - not on the date, not on the minute, not on the
Expiry - so partitioning it by any of those would write one identical copy per partition
and invite twenty-four of them to drift.

Three corners per (strike, side): the low end of the shared Forward domain, the strike,
and the high end. A Payoff is flat, then straight, and bends exactly once, so those three
points describe it exactly and linear interpolation between them reconstructs it without
error. A sampled grid stores the same straight segment many times over and still cuts the
corner unless a sample lands precisely on the strike - which is invisible on a chart,
because a four-Leg sum with four rounded corners still looks plausible.

**Every row sits on one shared, absolute Forward domain**, whose bounds are published in
the manifest. Legs are summed by adding their values at the same Forward, so a per-Leg
domain centred on its own strike sums points that are not the same point.
"""

MANIFEST = "manifest"
"""Which Expiries pair with which dates, and the bounds of the Forward domain (#67, #70).

**Unpartitioned**, and deliberately so: it is the index *over* the partitions, so keying
it by the same keys would make it answerable only by whoever already knew the answer. One
small file, read whole.

The Forward domain's two bounds live here rather than in a constant on either side,
because the writer that lays the corner points down and the reader that interpolates
between them have to agree on where the outer two sit. A constant in the reader agrees
until the day the writer's changes - and then it disagrees silently, by interpolating
over a segment that is not the segment that was stored.
"""

DERIVATION_VERSION = "v1"
"""What the stored numbers were derived by, carried in every dataset root's name.

In the name and not in a column, because a column can only be filtered on - it cannot
let two versions coexist. As a root, re-deriving writes `chain_v2` alongside `chain_v1`,
serving switches by pointing at the other one, and rolling back points back. A full
rebuild of the twenty-four days is about thirty-four seconds, so keeping the old root is
cheap and deleting it is a separate, unhurried decision.

Bump this when the meaning of a stored figure changes - a new pricing model, a changed
Greek convention - and not when a column is added that nothing yet reads.
"""

CACHE_ROOT = Path(os.environ.get("PAYOFF_CACHE", Path.home() / ".cache" / "convex-hedge-payoff"))
"""Where partitions fetched from S3 are kept.

Polars' cloud reader does **not** cache: a plain `scan_parquet("s3://...")` re-fetches on
every scan, and a trader dragging the time control makes one per frame. So a partition is
downloaded once and scanned from disk after that.

On a host with an ephemeral filesystem this is cold after every restart, which is correct
but worth knowing - the first request pays the fetch.
"""


def dataset_root(root: Path | str, dataset: str = CHAIN) -> Path:
    """Where one dataset's tree begins: its name, then the derivation version.

    Split out from `partition_path` only because the unpartitioned datasets #64 adds -
    the payoff corners, the manifest - need the versioned root without any keys under it.
    Both still spell the path in this one module.
    """
    return Path(root) / f"{dataset}_{DERIVATION_VERSION}"


def scan(root: Path | str, dataset: str = CHAIN) -> pl.LazyFrame:
    """A lazy view over every partition of `dataset` under `root`.

    Lazy on purpose, and not merely as an implementation detail: the caller composes a
    filter and a projection onto this frame, and Polars pushes both down into the parquet
    reader, so an as-of query at 12:00 reads neither the afternoon's row groups nor the
    columns it did not ask for.

    `root` is the runtime root, holding one versioned tree per dataset, and it is a local
    path. Fetching from S3 is `fetch`'s job, so that everything above this line is
    testable without a bucket, credentials or a network.
    """
    return pl.scan_parquet(f"{dataset_root(root, dataset)}/{PART_GLOB}", hive_partitioning=True)


def partition_path(
    root: Path | str, *, asset: str, date: str, expiry: str, dataset: str = CHAIN
) -> Path:
    """Where one day of one expiry lives, in Hive's `key=value` convention.

    One function rather than an f-string at each call site, because the reader and the
    writer have to agree on this exactly - a mismatch does not raise, it silently scans
    nothing. That is also why the key order is fixed here and not left to the caller's
    keyword order: a tree written expiry-above-date reads back byte-identical rows, so
    nothing downstream of this line can notice the mistake. `tests/test_store.py` spells
    the expected path out literally rather than calling this, which is the only way the
    agreement is actually checked rather than assumed.
    """
    return dataset_root(root, dataset) / f"asset={asset}" / f"date={date}" / f"expiry={expiry}"


@lru_cache(maxsize=1)
def runtime_root() -> Path:
    """The local root to scan, fetching from S3 first if that is where the day lives.

    `PAYOFF_RUNTIME` names it: an `s3://` URI is mirrored into `CACHE_ROOT`, and anything
    else is used as-is. Local by default so the test suite, the notebook and a developer
    with no AWS account all work without configuration.
    """
    configured = os.environ.get("PAYOFF_RUNTIME")
    if configured is None:
        return Path(__file__).resolve().parents[2] / "Data" / "runtime"
    if not configured.startswith("s3://"):
        return Path(configured)
    return fetch(configured)


def fetch(uri: str, cache: Path | None = None) -> Path:
    """Mirror an `s3://bucket/prefix` tree into the local cache and return its root.

    Objects already present are not re-fetched. The day is immutable, so a partition that
    exists locally cannot be out of date - and if the bucket is rebuilt the cache is
    cleared, which is a deployment step rather than a runtime check.

    `boto3` is imported here rather than at module scope so that nothing in the read path
    requires it to be installed until an S3 root is actually configured.
    """
    import boto3

    bucket, _, prefix = uri.removeprefix("s3://").partition("/")
    root = (cache or CACHE_ROOT) / bucket / prefix
    client = boto3.client("s3")

    pages = client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix)
    for page in pages:
        for entry in page.get("Contents", ()):
            key = entry["Key"]
            if not key.endswith(".parquet"):
                continue
            local = root / Path(key).relative_to(prefix)
            if local.exists():
                continue
            local.parent.mkdir(parents=True, exist_ok=True)
            client.download_file(bucket, key, str(local))

    return root

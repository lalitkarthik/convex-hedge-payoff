"""Where the derived day is kept, and how it is read.

The engine derives everything it serves - the forward and discount by put-call parity
(#51), the volatility by Newton (#52), the Greeks from Black-76 (#53). On the sample day
that costs **1.4 s**, and a process that pays it at every start pays it for nothing: the
day is immutable. So a job derives once and writes here, and the API only reads.

That is #23 story 48 - *"the Chain served from one derived data file loaded at boot, so
that the deployment is a static artefact rather than a database to operate"* - with two
qualifications. The artefact lives in S3 rather than in the repository, and it is
**Hive-partitioned**:

    chain/underlying=NIFTY/expiry=2026-02-10/date=2026-01-27/part-0.parquet

The partition keys are in the **path**, so they cost nothing to store, a filter on one
skips whole files before a byte of column data is read, and a second trading day or a
second expiry is a new prefix rather than a migration.

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

CACHE_ROOT = Path(os.environ.get("PAYOFF_CACHE", Path.home() / ".cache" / "convex-hedge-payoff"))
"""Where partitions fetched from S3 are kept.

Polars' cloud reader does **not** cache: a plain `scan_parquet("s3://...")` re-fetches on
every scan, and a trader dragging the time control makes one per frame. So a partition is
downloaded once and scanned from disk after that.

On a host with an ephemeral filesystem this is cold after every restart, which is correct
but worth knowing - the first request pays the fetch.
"""


def scan(root: Path | str) -> pl.LazyFrame:
    """A lazy view over every partition under `root`.

    Lazy on purpose, and not merely as an implementation detail: the caller composes a
    filter and a projection onto this frame, and Polars pushes both down into the parquet
    reader, so an as-of query at 12:00 reads neither the afternoon's row groups nor the
    columns it did not ask for.

    `root` is a local path. Fetching from S3 is `local_partition`'s job, so that
    everything above this line is testable without a bucket, credentials or a network.
    """
    return pl.scan_parquet(f"{Path(root)}/{PART_GLOB}", hive_partitioning=True)


def partition_path(root: Path | str, *, underlying: str, expiry: str, date: str) -> Path:
    """Where one day of one expiry lives, in Hive's `key=value` convention.

    One function rather than an f-string at each call site, because the reader and the
    writer have to agree on this exactly - a mismatch does not raise, it silently scans
    nothing.
    """
    return (
        Path(root) / f"underlying={underlying}" / f"expiry={expiry}" / f"date={date}"
    )


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

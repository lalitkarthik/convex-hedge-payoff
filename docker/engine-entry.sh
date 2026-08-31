#!/bin/sh
set -e

MANIFEST=/app/Data/runtime/manifest_v1/part-0.parquet

if [ ! -f "$MANIFEST" ]; then
  echo "runtime tree absent - deriving 24 dates (about 50s, once)"
  python scripts/build_runtime.py
fi

if [ "$RUNTIME_CHECK" = "1" ]; then
  echo "reconciling the stored tree against a fresh derivation"
  python scripts/build_runtime.py --check
fi

exec uvicorn payoff.api:app --host 0.0.0.0 --port 8000

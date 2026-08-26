"""Write `web/openapi.json` from the app's own schema.

The frontend's wire types are **generated, not hand-written**: this file feeds
`openapi-typescript`, which writes `web/lib/api-types.ts`. So a field renamed in
`models.py` becomes a compile error in the browser code rather than an `undefined` in
front of a trader.

Committed rather than fetched at build time, for one practical reason: `bun run build`
then needs no running Python server, and a frontend-only pull request stays a
frontend-only pull request. The cost is that the file can go stale, which
`tests/test_openapi_contract.py` exists to catch.

Run this whenever `models.py` or `api.py` changes, and commit both outputs:

    python scripts/dump_openapi.py
    cd web && bun run codegen
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from payoff.api import app  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "web" / "openapi.json"


def main() -> None:
    # Indented and key-sorted: this file is read in diffs far more often than by a
    # program, and a one-line schema turns every field addition into an unreviewable
    # 40 KB change.
    OUT.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")

    schema = json.loads(OUT.read_text())
    print(f"{OUT.relative_to(Path.cwd())}: {len(schema['paths'])} paths, "
          f"{len(schema['components']['schemas'])} schemas")


if __name__ == "__main__":
    main()

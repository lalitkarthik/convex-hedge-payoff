"""The one thing the suite needs that the repository cannot commit.

`Data/runtime/` is **derived, not authored**: `scripts/build_runtime.py` writes it and
`.gitignore` keeps it out, because a build product in version control is a second copy of
the truth that drifts from the first. So a fresh clone has the committed raw data and no
runtime tree at all - and since #66 the serving path reads the tree and nothing else.

README.md promises that "tests and CI need no external setup". Both statements have to
hold at once, and the only way they can is if the suite builds what it needs itself. This
fixture is that build.

**It builds three dates, not twenty-four.** #67 derives every trading date and a full
build measures **47.7 s** - a minute added to every `pytest` on a suite that otherwise
runs in a few seconds, which is how a suite stops being run. The three are chosen to
cover the shape of the dataset rather than a sample of it:

| `2026-01-07` | the sparse end: 12 strikes over 150 of the session's 376 minutes |
| `2026-01-27` | the dense anchor: 94 strikes over 376, and every published figure   |
| `2026-02-10` | Expiry itself, where `dte_days` reaches 0 and `T` with it           |

The other twenty-one differ from these in row count and in nothing else, and a test that
asserted one of them would be asserting the same code path a fourth time at two seconds a
go. That every date builds is asserted where it is cheap to assert - `tests/test_seed.py`
grades the twenty-four-date enumeration and the reconstructed clock against the Oracle on
all 517,672 of its rows, without deriving anything.

**The build is skipped when the tree is already the one this code would write.** Not when
it merely exists: a tree left behind by an older checkout would otherwise be served to
every assertion below without anything noticing, which is the exact failure
`build_runtime.py --check` exists to catch in production. So the skip is keyed on a
digest of everything that decides a stored figure - the derivation version, the dates,
the size and mtime of the two raw files, and the **source of every module** under `src/`
and `scripts/`. Change a formula and the digest changes with it; change a comment and it
changes too, which is the harmless direction to be wrong in.

**The serving path itself has no fallback**, deliberately. `chain.MissingRuntimeTree`
names this command and stops. A serving path that quietly re-derived would put the
derivation back into the first request - the cost #64 exists to remove - and would hide a
misconfigured deployment behind an answer that looked right.
"""

import hashlib
import os
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_runtime  # noqa: E402  - scripts/ is not a package

SPARSE_DATE = date(2026, 1, 7)
ANCHOR_DATE = date(2026, 1, 27)
EXPIRY_DATE = date(2026, 2, 10)

DATES = (SPARSE_DATE, ANCHOR_DATE, EXPIRY_DATE)
"""The dates the suite reads. Anything asserting a fourth has to build it itself."""

STAMP = ".build-stamp"
"""Written into the runtime root after a successful build, and never into a partition -
a half-written tree must not be able to leave a stamp that says it is finished."""


def build_digest(dates: tuple[date, ...]) -> str:
    """Everything that could change a stored figure, in one hex string.

    The raw files by size and mtime rather than by content: they are 43 MB and hashing
    them on every collection would cost more than the build this is avoiding.
    """
    digest = hashlib.sha256()
    digest.update(build_runtime.store.DERIVATION_VERSION.encode())
    digest.update(",".join(str(day) for day in dates).encode())

    for raw in (build_runtime.seed.OPTIONS_FILE, build_runtime.seed.INDEX_FILE):
        stat = raw.stat()
        digest.update(f"{raw.name}:{stat.st_size}:{stat.st_mtime_ns}".encode())

    for source in sorted((ROOT / "src").rglob("*.py")) + sorted((ROOT / "scripts").glob("*.py")):
        digest.update(source.read_bytes())

    return digest.hexdigest()


@pytest.fixture(scope="session", autouse=True)
def runtime_tree() -> Path:
    """Derive the dates the suite reads into the default runtime root, before anything
    reads them.

    Skipped when `PAYOFF_RUNTIME` is set: that names a tree somebody chose on purpose -
    an S3 mirror, a prebuilt cache in CI - and overwriting it would be the fixture
    deciding something the operator already decided.
    """
    if os.environ.get("PAYOFF_RUNTIME"):
        return Path(os.environ["PAYOFF_RUNTIME"])

    root = build_runtime.DEFAULT_ROOT
    stamp = root / STAMP
    digest = build_digest(DATES)
    if stamp.exists() and stamp.read_text().strip() == digest:
        return root

    build_runtime.main(root, DATES)
    stamp.write_text(digest)
    return root

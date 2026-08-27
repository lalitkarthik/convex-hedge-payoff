"""The one thing the suite needs that the repository cannot commit.

`Data/runtime/` is **derived, not authored**: `scripts/build_runtime.py` writes it and
`.gitignore` keeps it out, because a build product in version control is a second copy of
the truth that drifts from the first. So a fresh clone has the committed raw data and no
runtime tree at all - and since #66 the serving path reads the tree and nothing else.

README.md promises that "tests and CI need no external setup". Both statements have to
hold at once, and the only way they can is if the suite builds what it needs itself. This
fixture is that build: once per session, from the committed sample, into the default root.
It is the same call `python scripts/build_runtime.py` makes.

**Unconditionally, not only when the tree is missing.** A tree left behind by an older
checkout would otherwise be served to every assertion below without anything noticing -
which is the exact failure `build_runtime.py --check` exists to catch in production, and
it would be perverse for the test suite to be the one place it goes unchecked. The build
costs 1.4 s once; a stale tree costs an afternoon.

**The serving path itself has no fallback**, deliberately. `chain.MissingRuntimeTree`
names this command and stops. A serving path that quietly re-derived would put the 1.4 s
back into the first request - the cost #64 exists to remove - and would hide a
misconfigured deployment behind an answer that looked right.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_runtime  # noqa: E402  - scripts/ is not a package


@pytest.fixture(scope="session", autouse=True)
def runtime_tree() -> Path:
    """Derive the anchor day into the default runtime root, before anything reads it.

    Skipped when `PAYOFF_RUNTIME` is set: that names a tree somebody chose on purpose -
    an S3 mirror, a prebuilt cache in CI - and overwriting it would be the fixture
    deciding something the operator already decided.
    """
    if os.environ.get("PAYOFF_RUNTIME"):
        return Path(os.environ["PAYOFF_RUNTIME"])
    build_runtime.main()
    return build_runtime.DEFAULT_ROOT

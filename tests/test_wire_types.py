"""`web/lib/types.ts` against the schema it claims to mirror.

The frontend's wire types were **meant to be generated** from `web/openapi.json` by
`openapi-typescript`, so that a field renamed in `models.py` becomes a compile error in
the browser rather than an `undefined` in front of a trader. The npm registry was
unreachable when this landed and the generator could not be installed, so the file is
hand-written for now.

Hand-written is fine. Hand-written *and unchecked* is not: `test_openapi_contract.py`
guards the schema against the app, which leaves exactly one gap - a rename that is dumped
into the schema correctly and never reflected in TypeScript. Both tests pass, the build
is green, and the field reads `undefined` at runtime.

This closes that gap by comparing the field names directly. It is a stand-in and says so:
**when `openapi-typescript` can be installed, generate `lib/api-types.ts` and delete this
file** - a generator does this job properly, including types and nullability, which a
regex over an interface body cannot.
"""

import json
import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "web"
TYPES_FILE = WEB / "lib" / "types.ts"
SCHEMA_FILE = WEB / "openapi.json"

#: The response and request shapes the browser actually reads. `Leg` is absent
#: deliberately - it is a server-internal type that never crosses the wire.
MIRRORED = [
    "SessionResponse",
    "SummaryResponse",
    "ChainResponse",
    "ChainRow",
    "ChainQuote",
    "LegRequest",
    "AnalysisRequest",
    "AnalysisResponse",
    "Curve",
    "Metrics",
    "LegGreeks",
    "PresetResponse",
]


def typescript_fields(source: str, name: str) -> set[str]:
    """The property names declared on one exported interface.

    Deliberately crude - it reads names and nothing else. The types themselves are what a
    generator would check; this only catches the failure a generator makes impossible,
    which is a field that is present on one side and absent on the other.
    """
    body = re.search(rf"export interface {name} \{{(.*?)\n\}}", source, re.S)
    assert body, f"web/lib/types.ts declares no interface {name}"

    # Strip comments first, so a field named inside a docstring is not counted as one.
    text = re.sub(r"/\*.*?\*/", "", body.group(1), flags=re.S)
    text = re.sub(r"//.*", "", text)
    return set(re.findall(r"^\s{2}(\w+)\??:", text, re.M))


@pytest.fixture(scope="module")
def schema() -> dict:
    assert SCHEMA_FILE.exists(), "run scripts/dump_openapi.py"
    return json.loads(SCHEMA_FILE.read_text())["components"]["schemas"]


@pytest.fixture(scope="module")
def source() -> str:
    return TYPES_FILE.read_text()


@pytest.fixture(scope="module")
def code(source: str) -> str:
    """The declarations with the prose stripped out.

    The two absence tests below search for names that the file's own docstring *names*,
    because it explains why they were removed. Searching the raw text would make the
    documentation fail the test that the documentation describes.
    """
    without_blocks = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"//.*", "", without_blocks)


@pytest.mark.parametrize("name", MIRRORED)
def test_the_typescript_mirror_declares_exactly_the_schemas_fields(name, schema, source):
    """Equality, not containment, and in both directions.

    A **missing** field is the obvious failure: the page reads `undefined` where a number
    should be, and renders "NaN" or an empty cell. An **extra** one is the quieter half -
    TypeScript happily types a property the server has never sent, so the code compiles,
    the reviewer sees a plausible field name, and it is `undefined` every time.
    """
    assert typescript_fields(source, name) == set(schema[name]["properties"]), (
        f"{name} has drifted from the schema - regenerate web/openapi.json "
        f"with scripts/dump_openapi.py and update web/lib/types.ts to match"
    )


def test_the_camelcase_mirror_is_gone(code):
    """One vocabulary on the wire, and it is the server's.

    There used to be a `Metrics` with `maxProfit` beside the `max_profit` the server
    sends, adapted at the boundary. Two names for one field is where a rename gets lost:
    the adapter keeps compiling, and the new field arrives into a mapping that does not
    mention it.
    """
    for camel in ("maxProfit", "maxLoss", "netPremium", "rewardRisk", "entryPremium", "optionType"):
        assert camel not in code, f"{camel} is a second name for a field the server already names"


def test_the_fixture_artefact_is_gone(code):
    """`contract_greeks` carried all five Greeks per strike per side.

    It existed only so the skeleton's Greeks tab could work with no server to ask, and it
    was labelled a fixture artefact rather than a proposed contract change. `/analyse`
    returns them now, so a type that still declared it would be advertising a field
    nothing sends.
    """
    assert "contract_greeks" not in code

"""The committed schema, and the guard that keeps it honest.

`web/lib/api-types.ts` is **generated** from `web/openapi.json`, which is generated from
the pydantic models in `models.py`. That chain is what makes a seam change break the
frontend's build instead of producing an `undefined` in front of a trader - but only for
as long as the committed copy matches the app.

It is committed rather than fetched at build time so that `bun run build` needs no
running backend: CI typechecks the frontend without standing a Python server up, and a
frontend-only pull request stays a frontend-only pull request.

The cost of committing it is that it can go stale, which is exactly what this file
prevents. **If this test fails, run `python scripts/dump_openapi.py`** - the schema
changed and the generated types have not caught up.
"""

import json
from pathlib import Path

import pytest

from payoff.api import app

SCHEMA_FILE = Path(__file__).resolve().parents[1] / "web" / "openapi.json"


@pytest.fixture(scope="module")
def committed() -> dict:
    assert SCHEMA_FILE.exists(), f"{SCHEMA_FILE} is missing - run scripts/dump_openapi.py"
    return json.loads(SCHEMA_FILE.read_text())


def test_the_committed_schema_is_the_one_the_app_serves(committed):
    """The whole point of the file. Equality, not a subset.

    A subset check would pass while the schema carried a route that no longer exists,
    and the generated client would keep offering a method that 404s.
    """
    assert committed == app.openapi(), (
        "web/openapi.json is stale - run `python scripts/dump_openapi.py` and commit it"
    )


def test_every_route_the_frontend_calls_is_in_it(committed):
    """Named explicitly, so deleting one is a decision rather than a diff nobody reads.

    These six are the entire surface the browser talks to. A seventh appearing here
    without a frontend that calls it is fine; one of these six disappearing is not.

    `/summary` joined them in #69: the header's four figures come off it, and on
    `/analyse` it **replaced** the `/chain` call that page used to make to render them.
    """
    paths = committed["paths"]
    assert set(paths) >= {
        "/session",
        "/summary",
        "/chain",
        "/analyse",
        "/presets",
        "/presets/{name}",
    }

    assert "get" in paths["/session"]
    assert "get" in paths["/summary"]
    assert "get" in paths["/chain"]
    assert "post" in paths["/analyse"]


def test_the_schemas_the_client_generates_types_from_are_all_present(committed):
    """The response models, by name.

    `openapi-typescript` names its exports after these, so a rename here is a rename in
    `api-types.ts` and a compile error in the frontend - which is the failure mode this
    whole arrangement is buying.
    """
    schemas = committed["components"]["schemas"]
    assert {
        "SessionResponse",
        "SummaryResponse",
        "ChainResponse",
        "ChainRow",
        "ChainQuote",
        "AnalysisRequest",
        "AnalysisResponse",
        "LegRequest",
        "LegGreeks",
        "Curve",
        "Metrics",
        "PresetResponse",
    } <= set(schemas)


def test_the_two_conventions_that_surprise_survive_into_the_schema(committed):
    """`max_profit` is nullable and `table` exists - the two a client gets wrong.

    `null` means **Unlimited** (CONTEXT.md), never an infinity token and never a blank.
    A schema that lost the nullability would have the generated type say `number`, and
    the client would render "0" for an unbounded gain.
    """
    schemas = committed["components"]["schemas"]

    assert "table" in schemas["AnalysisResponse"]["properties"]

    max_profit = schemas["Metrics"]["properties"]["max_profit"]
    assert "anyOf" in max_profit, "max_profit must stay nullable - null is Unlimited"
    assert {"type": "null"} in max_profit["anyOf"]

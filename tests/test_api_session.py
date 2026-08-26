"""Seam one, widened: what a client needs *before* it can ask for anything else.

Every other endpoint takes a `moment`, and until now there was no way to learn which
moments exist. The frontend skeleton papered over that with a `session.json` fixture
written by a build script - which meant the list of tradeable minutes was a property of
a generated file rather than of the engine, and could drift from it silently.

So the assertions here are mostly **agreement** assertions: the session's moments are the
ones `/chain` answers on, its expiry is the one `/chain` publishes, its presets are the
ones `/presets` offers. A session that describes a day the rest of the API does not serve
is worse than no session at all - it fails at the point a trader clicks, not here.

As everywhere in this file's neighbours, nothing imports `chain` or `presets`: what is
graded is what comes back over HTTP.
"""

import pytest
from fastapi.testclient import TestClient

from payoff.api import app

ANCHOR = "2026-01-27T06:30:00"
"""06:30 UTC = 12:00 IST, the minute every published figure was measured at."""


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="module")
def session(client: TestClient) -> dict:
    response = client.get("/session")
    assert response.status_code == 200, response.text
    return response.json()


def test_the_session_offers_every_minute_that_quoted(session):
    """376, and not the 391 minutes a naive clock would produce.

    The sample day runs 09:15 to 15:30 IST, which is 376 minutes only because the
    minutes that quoted nothing are absent. Deriving the list from a clock instead of
    from the data would offer a trader fifteen stops that return an empty Chain.
    """
    assert session["moment_count"] == 376
    assert len(session["moments"]) == 376


def test_the_moments_are_ordered_and_bracketed_by_their_own_bounds(session):
    """The time control is a slider, so the order is load-bearing rather than cosmetic.

    Published bounds that disagree with the list they bound would put the slider's ends
    somewhere other than the day's ends, and nothing on screen would look wrong.
    """
    moments = session["moments"]
    assert moments == sorted(moments)
    assert session["first_moment"] == moments[0]
    assert session["last_moment"] == moments[-1]


def test_every_published_moment_is_one_the_chain_endpoint_answers_on(session, client):
    """The agreement that justifies the endpoint.

    Spot-checked at both ends and the anchor rather than all 376: the failure this
    guards is a *format* mismatch - a moment published in one spelling and accepted in
    another - and that breaks at the first stop, not at the four-hundredth.
    """
    assert ANCHOR in session["moments"], "the anchor minute must be reachable"

    for moment in (session["first_moment"], ANCHOR, session["last_moment"]):
        response = client.get("/chain", params={"moment": moment})
        assert response.status_code == 200, f"{moment} -> {response.text}"
        assert response.json()["moment"] == moment


def test_the_expiry_is_the_one_the_chain_publishes(session, client):
    """One expiry in this dataset, so a calendar spread has no second Leg to reference.

    Stated in two places because the header reads it from here and the Chain reads it
    from there; if they could disagree, a trader would see one expiry above a chain of
    another.
    """
    assert session["expiry"] == "10FEB26"

    chain = client.get("/chain", params={"moment": ANCHOR}).json()
    assert session["expiry"] == chain["expiry"]


def test_the_preset_names_are_the_ones_the_preset_endpoint_offers(session, client):
    """The picker renders from the session; clicking one calls `/presets/{name}`.

    A name in the session that the builder does not know is a button that 404s, and it
    is the sort of thing that only shows up when someone clicks the fifth one.
    """
    expected = ["straddle", "strangle", "iron_condor", "credit_spread", "iron_fly"]
    assert session["presets"] == expected
    assert session["presets"] == client.get("/presets").json()["presets"]

    for name in session["presets"]:
        response = client.get(f"/presets/{name}", params={"moment": ANCHOR})
        assert response.status_code == 200, f"{name} -> {response.text}"
        assert response.json()["legs"], f"{name} built no Legs"


def test_the_strike_bounds_contain_every_strike_the_chain_quotes(session, client):
    """23,300 to 27,950 - what the chart's x-axis and any strike input are sized against.

    Asserted as a containment rather than by equality at one minute, because the bounds
    are the day's and a single minute quotes fewer strikes than the day does.
    """
    assert session["strike_min"] == 23300.0
    assert session["strike_max"] == 27950.0

    chain = client.get("/chain", params={"moment": ANCHOR}).json()
    strikes = [row["strike"] for row in chain["rows"]]
    assert min(strikes) >= session["strike_min"]
    assert max(strikes) <= session["strike_max"]


def test_no_field_is_null(session):
    """A session is the one response a client cannot proceed without.

    `None` anywhere here means a frontend renders a slider with no stops or a picker with
    no names, and the symptom appears three screens away from the cause.
    """
    for name, value in session.items():
        assert value is not None, f"{name} is null"
        assert value != [], f"{name} is empty"

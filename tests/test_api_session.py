"""Seam one, widened: what a client needs *before* it can ask for anything else.

Every other endpoint takes a `moment`, and until now there was no way to learn which
moments exist. The frontend skeleton papered over that with a `session.json` fixture
written by a build script - which meant the list of tradeable minutes was a property of
a generated file rather than of the engine, and could drift from it silently.

So the assertions here are mostly **agreement** assertions: the session's moments are the
ones `/chain` answers on, its expiry is the one `/chain` publishes, its presets are the
ones `/presets` offers. A session that describes a day the rest of the API does not serve
is worse than no session at all - it fails at the point a trader clicks, not here.

**Widened again for #68**, and for the same reason a third time. Two dropdowns above the
Chain populate from `dates` and `expiries` here, so the agreement now has to hold across
every pair either dropdown can offer: every date it lists must be one `/chain` serves,
and every Expiry it lists against a date must be one `/chain` serves *on that date*. A
list built by walking a tree, or by a build script writing a file, is exactly the drift
this endpoint exists to prevent - and a pairing that is merely plausible is worse than
none, because it fails at the click rather than here.

`tests/conftest.py` builds three dates and says why, so the assertions below are written
against **what the store holds** rather than against twenty-four. That is not a weakening:
the claim being graded is that the two agree, and it is false in the same way at three
dates as at twenty-four.

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


# --------------------------------------------------------------------------------------
# #68: the two dropdowns, and the agreement that lets them be dropdowns at all.
# --------------------------------------------------------------------------------------


def session_for(client: TestClient, **asked: str) -> dict:
    """A session for one pair, asked for the way the dropdowns ask for it."""
    response = client.get("/session", params=asked)
    assert response.status_code == 200, response.text
    return response.json()


def test_the_session_names_the_pair_it_describes_and_lists_what_else_exists(session):
    """The four fields the two dropdowns are built out of, and how they relate.

    `date` and `expiry` are the **selected** pair; `dates` and `expiries` are what the
    two lists offer. The selected one being a member of its own list is not a tautology
    worth skipping: a resolved pair that is not in the list a client renders shows a
    dropdown with nothing highlighted, and a trader cannot tell what they are looking at.
    """
    assert session["dates"] == sorted(session["dates"]), "a dropdown reads in order"
    assert session["expiries"] == sorted(session["expiries"])

    assert session["date"] in session["dates"]
    assert session["expiry"] in session["expiries"]

    assert session["date"] == ANCHOR[:10], "a link naming no date opens on the anchor"


def test_every_date_it_lists_is_one_the_chain_endpoint_answers_on(session, client):
    """The agreement, in the direction the date dropdown is read.

    A date offered here that `/chain` will not serve is a menu entry that produces an
    empty screen, and it fails at the click rather than at the list. Swept across every
    date rather than spot-checked, because the list is short by construction - it is the
    manifest, and the manifest is one row per pair.

    Each date is asked for at **its own** first moment, taken from its own session. A
    moment from another day would be the more obvious test and would grade the wrong
    thing: it would pass on any implementation that ignored `date` entirely.
    """
    for day in session["dates"]:
        theirs = session_for(client, date=day)
        assert theirs["date"] == day, "the date asked for is the date described"

        response = client.get("/chain", params={"moment": theirs["first_moment"], "date": day})
        assert response.status_code == 200, f"{day} -> {response.text}"
        assert response.json()["moment"] == theirs["first_moment"]


def test_every_expiry_it_lists_against_a_date_is_one_the_chain_serves_on_that_date(
    session, client
):
    """The agreement in the direction the Expiry dropdown is read - **per date**.

    The pairing is what is being graded, not the list. One Expiry exists in this dataset,
    so every assertion below happens to run once; none of them is written in a way that
    would still pass if the pairing were dropped and a single Expiry assumed, because
    each is a lookup keyed by the date it belongs to.

    `/chain` echoing the Expiry back is what makes the round trip closed: the label the
    dropdown showed, the label the URL carried and the label the Chain published are one
    string, compared without a conversion in the middle.
    """
    for day in session["dates"]:
        theirs = session_for(client, date=day)
        assert theirs["expiries"], f"{day} is in the store, so something traded on it"

        for expiry in theirs["expiries"]:
            response = client.get(
                "/chain",
                params={"moment": theirs["first_moment"], "date": day, "expiry": expiry},
            )
            assert response.status_code == 200, f"{day}/{expiry} -> {response.text}"
            assert response.json()["expiry"] == expiry


def test_a_date_carries_its_own_minutes_rather_than_the_one_before_it(session, client):
    """Picking a date has to move the time control too, and it is easy for it not to.

    7 January quoted 150 minutes and the anchor 376. A session endpoint that took a date
    and returned the anchor's minutes anyway would look completely correct - the dropdown
    would work, the header would update - right up to a trader dragging the slider past
    the 150th stop into minutes that day never had.
    """
    sparse = session_for(client, date="2026-01-07")

    assert sparse["moment_count"] == len(sparse["moments"])
    assert sparse["moment_count"] != session["moment_count"]
    assert all(stamp.startswith("2026-01-07") for stamp in sparse["moments"])
    assert sparse["first_moment"] == sparse["moments"][0]
    assert sparse["last_moment"] == sparse["moments"][-1]


def test_choosing_a_date_that_never_traded_the_held_expiry_resolves_to_a_pair_that_exists(
    session, client
):
    """#68's third criterion, and the reason the resolution lives on the server.

    A trader changes the date; the Expiry in the URL is one interaction behind, and on a
    dataset with more than one series it may be one the new date never traded. The pair
    that comes back is one the store holds - and because the client renders `date` and
    `expiry` rather than what it sent, the Chain is never empty and the dropdown is never
    showing a selection that is not in its own list.

    Asserted through an Expiry that exists nowhere in the dataset, which is the same
    branch a real mispairing takes and the only one this dataset can reach.
    """
    resolved = session_for(client, date="2026-01-07", expiry="10MAR26")

    assert resolved["date"] == "2026-01-07", "the date is what was clicked; it wins"
    assert resolved["expiry"] in resolved["expiries"]

    served = client.get(
        "/chain",
        params={
            "moment": resolved["first_moment"],
            "date": resolved["date"],
            "expiry": resolved["expiry"],
        },
    )
    assert served.status_code == 200, served.text
    assert served.json()["rows"], "a resolved pair is a Chain, not an empty one"


def test_a_link_naming_a_date_that_was_never_built_falls_back_rather_than_failing(client):
    """The session is how a client learns what exists, so it has to answer.

    A hand-edited or truncated link is the likeliest way to hold a date the store does
    not have, and an error page there teaches a trader nothing about which dates it does
    have. Falling back to the anchor shows a real day *and* hands over the list that
    would have been correct - which is the useful reply.
    """
    stray = session_for(client, date="1999-01-01")

    assert stray["date"] == ANCHOR[:10]
    assert stray["moments"], "a real day, not an empty session"
    assert "1999-01-01" not in stray["dates"]


def test_asking_the_chain_for_a_date_that_was_never_built_names_the_date(client):
    """The counterpart, and the opposite rule: `/chain` is asked for one specific thing.

    Strict rather than forgiving, because a Chain quietly served for a different day is
    indistinguishable on screen from the one that was asked for, while a session that
    resolves says which pair it resolved to.

    The date is deliberately one the dataset does not contain at all, rather than a
    trading date that merely has not been built yet. `conftest` builds a three-date
    subset for speed, so any real date reads as missing until someone runs a full build
    in the same tree - and then this test would fail for a reason unrelated to what it
    grades.

    The message is the point. Filtering the store to a date it does not hold yields an
    empty frame, and the first thing downstream to notice used to be the as-of slice,
    which reported `0 -- is not quoted at or before this moment` - a true sentence about
    a strike, in answer to a question about a date. #31 owns the body's shape; what is
    graded here is that the words identify the thing that is actually missing.
    """
    response = client.get("/chain", params={"moment": "2026-01-27T06:30:00", "date": "2026-03-16"})

    assert response.status_code == 404, response.text
    detail = response.json()["detail"]
    assert "2026-03-16" in detail, f"the date that is missing has to be in it: {detail}"
    assert "quoted" not in detail, "the old message blamed a strike for a missing date"


def test_asking_the_chain_for_an_expiry_that_date_did_not_trade_names_what_it_did(
    session, client
):
    """The pairing, refused at the other end from where the dropdown prevents it.

    A dropdown that only offers real pairs is not a guarantee: a link is hand-editable
    and the API is reachable without one. Naming what the date *did* trade is what makes
    the refusal actionable rather than merely correct.
    """
    response = client.get(
        "/chain",
        params={"moment": ANCHOR, "date": ANCHOR[:10], "expiry": "10MAR26"},
    )

    assert response.status_code == 404, response.text
    detail = response.json()["detail"]
    assert "10MAR26" in detail
    assert session["expiry"] in detail, f"say what would have worked: {detail}"


def test_an_expiry_that_is_not_a_label_is_refused_rather_than_guessed_at(client):
    """422 and not 404: nothing was looked up, so nothing is missing.

    One spelling on the wire, and it is the one the dropdown shows and the URL carries.
    Reading an ISO date here as well would give the same Expiry two spellings, and two
    links describing one view would not compare equal.
    """
    response = client.get("/chain", params={"moment": ANCHOR, "expiry": "2026-02-10"})

    assert response.status_code == 422, response.text
    assert "10FEB26" in response.json()["detail"], "say what the form is"

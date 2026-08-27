"""Seam six: the header, and the artifact behind it (#69).

Spot, the Forward, the Discount Factor and the at-the-money volatility belong to the
**minute**, not to the strike. In the stored Chain they repeat across every strike of that
minute - about 196 rows on a dense one - so a header that read them there opened the
artifact holding 1,062,024 rows to take four numbers out of it. `/summary` reads a row of
375 a day instead, and dragging the time control across a session turns 375 reads of the
large file into 375 lookups in a small one.

**Which makes the agreement the only thing worth grading here.** Two artifacts describing
one minute that can disagree are worse than one artifact - the header would contradict the
table underneath it and nothing on screen would say which was right. So the assertions
below are almost entirely equalities against `/chain` at the same minute, swept across
every minute of two whole days rather than spot-checked: the sparse early date, where 12
strikes traded across 150 minutes, and Expiry day, where time to Expiry reaches zero and
the last minute implies no volatility at all. Those are the two shapes a reduction gets
wrong, and neither of them is the anchor.

Compared with `==` rather than a tolerance, deliberately. Both sides are the same float64,
read out of files the build wrote in one pass, and serialised by the same encoder. A
difference of any size means they were produced twice rather than reduced once, which is
the arrangement this ticket exists to avoid.

As everywhere in this file's neighbours, nothing imports `chain`: what is graded is what
comes back over HTTP.
"""

import pytest
from fastapi.testclient import TestClient

from payoff.api import app

ANCHOR = "2026-01-27T06:30:00"
"""06:30 UTC = 12:00 IST, the minute every published figure was measured at."""

SPARSE = "2026-01-07"
"""The sparse end of the dataset: 12 strikes across 150 of the session's 376 minutes."""

EXPIRY_DAY = "2026-02-10"
"""Expiry itself, where `dte_days` reaches 0 - and where the last minute's prints depend
on no volatility at all, so every strike in it carries a null."""

EXPIRY = "10FEB26"


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def session_for(client: TestClient, day: str) -> dict:
    response = client.get("/session", params={"date": day})
    assert response.status_code == 200, response.text
    return response.json()


def summary_at(client: TestClient, moment: str, day: str) -> dict:
    response = client.get("/summary", params={"moment": moment, "date": day, "expiry": EXPIRY})
    assert response.status_code == 200, f"{moment} -> {response.text}"
    return response.json()


def chain_at(client: TestClient, moment: str, day: str) -> dict:
    response = client.get("/chain", params={"moment": moment, "date": day, "expiry": EXPIRY})
    assert response.status_code == 200, f"{moment} -> {response.text}"
    return response.json()


def test_the_summary_carries_the_four_figures_the_header_shows(client):
    """What the endpoint is for, at the one minute every published figure was measured at.

    The at-the-money strike is 25,200 while Spot reads 25,100.25, and that is the reason
    the Forward is on screen at all: the basis is +118.87 here, more than two 50-point
    intervals, so the money is two strikes away from where Spot would have put it. A
    header that published a volatility without the strike it belongs to would be
    publishing a number nobody could check.
    """
    header = summary_at(client, ANCHOR, ANCHOR[:10])

    assert header["moment"] == ANCHOR, "echoed back as it was asked for"
    assert header["date"] == ANCHOR[:10]
    assert header["expiry"] == EXPIRY

    assert header["spot"] == 25_100.25
    assert header["forward"] == pytest.approx(25_219.12, abs=0.01)
    assert 0.9 < header["discount"] < 1.0, "a discount factor, never a rate"
    assert header["forward_method"] == "parity_fit"

    assert header["atm_strike"] == 25_200.0, "nearest the Forward - Spot would say 25,100"
    assert 0.0 < header["atm_iv"] < 1.0


@pytest.mark.parametrize("day, stride", [(SPARSE, 1), (EXPIRY_DAY, 3)])
def test_every_figure_is_identical_to_what_the_chain_reports_for_the_same_minute(
    client, day, stride
):
    """The assertion the split lives or dies on, over HTTP, across two whole days.

    Not a shape check. A reduction that took the wrong row of a minute, or the wrong
    side's volatility, or the last minute of the previous day, produces a header that is
    plausible everywhere and wrong somewhere - and these two days are where somewhere is:
    the sparse date has minutes in which almost nothing traded, and Expiry day has one in
    which no price implies any volatility.

    **The sparse date is swept whole; Expiry day is sampled through the session and swept
    whole across its close**, which is where `dte_days` reaches zero and the prints stop
    implying anything. The stride is a cost decision and not a hedge: an as-of read of a
    73,000-row day costs more the later in the session it lands, so a second full sweep
    would take a third of the suite's runtime to re-make an agreement that is already
    checked minute by minute on the day beside it and, below HTTP, on all 376 minutes of
    the anchor in `tests/test_store.py`.

    The at-the-money volatility is graded against **`ChainRow.iv` at that strike**, which
    is the number the table prints in the row the header points at. That is the pair a
    trader can actually see disagree.
    """
    stamps = session_for(client, day)["moments"]
    assert stamps, f"{day} is in the store, so something traded on it"

    for moment in sorted(set(stamps[::stride]) | set(stamps[-30:])):
        header = summary_at(client, moment, day)
        table = chain_at(client, moment, day)

        assert header["moment"] == table["moment"] == moment
        assert header["expiry"] == table["expiry"]
        for figure in ("spot", "forward", "discount", "forward_method"):
            assert header[figure] == table[figure], f"{figure} disagrees at {moment}"

        rows = {row["strike"]: row for row in table["rows"]}
        assert header["atm_strike"] in rows, f"the money is not in the Chain at {moment}"
        assert header["atm_iv"] == rows[header["atm_strike"]]["iv"], (
            f"the header's volatility is not the one the table prints at {moment}"
        )


def test_the_sparse_date_is_thin_and_answers_on_every_one_of_its_minutes(client):
    """The shape the sweep above is worth running on, stated so it cannot quietly change.

    150 minutes against the anchor's 376 and 12 strikes against 94. A reduction that
    assumed the dense day - a fixed strike grid, a minute that always quotes both sides -
    would pass on the anchor and fail here, which is why the fixture builds this date at
    all.
    """
    stamps = session_for(client, SPARSE)["moments"]
    assert len(stamps) == 150

    first, last = summary_at(client, stamps[0], SPARSE), summary_at(client, stamps[-1], SPARSE)
    assert first["date"] == last["date"] == SPARSE
    assert len(chain_at(client, stamps[0], SPARSE)["rows"]) <= 12, "the sparse end"


def test_expiry_day_serves_a_minute_whose_money_implies_no_volatility(client):
    """`null`, not zero and not an error - the same rule `ChainRow.iv` follows.

    At the last bar of Expiry day the price no longer depends on volatility, so no
    volatility reproduces it and every strike in that minute carries a null. A header that
    fabricated a number there would be publishing one a trader would size against; a
    header that raised would blank the screen on a minute the Chain serves perfectly well.

    Found by sweeping the close rather than by naming the stamp, so the test still means
    something if the dataset's last minute moves.
    """
    stamps = session_for(client, EXPIRY_DAY)["moments"]
    nulls = [
        moment
        for moment in stamps[-3:]
        if summary_at(client, moment, EXPIRY_DAY)["atm_iv"] is None
    ]
    assert nulls, "Expiry day must reach a minute where nothing is implied"

    for moment in nulls:
        table = chain_at(client, moment, EXPIRY_DAY)
        rows = {row["strike"]: row for row in table["rows"]}
        money = summary_at(client, moment, EXPIRY_DAY)["atm_strike"]
        assert rows[money]["iv"] is None, "and the table says the same thing about it"


def test_the_time_controls_stops_are_the_minutes_the_summary_answers_on(client):
    """One row per minute *is* one stop per minute, which is why the two come off one file.

    The session's moments are read off the summary now, so this is an agreement between
    the list a client renders and the rows behind it. A stop the header could not answer
    for is a slider position that blanks four figures, and it would fail at the drag
    rather than here.
    """
    for day in (SPARSE, ANCHOR[:10], EXPIRY_DAY):
        stamps = session_for(client, day)["moments"]
        assert stamps == sorted(stamps)
        for moment in (stamps[0], stamps[len(stamps) // 2], stamps[-1]):
            assert summary_at(client, moment, day)["moment"] == moment


def test_the_anchor_agrees_across_the_session_as_well_as_at_its_published_minute(client):
    """The dense day, sampled rather than swept.

    The two days above are swept because they are the awkward shapes; the anchor is the
    ordinary one, and every sixteenth minute of it is enough to catch a reduction that
    drifts through a session - an off-by-one in the minute, or a carried-forward row
    reaching the header - without paying 376 round trips for the third time in one file.
    """
    stamps = session_for(client, ANCHOR[:10])["moments"]

    for moment in stamps[::16]:
        header = summary_at(client, moment, ANCHOR[:10])
        table = chain_at(client, moment, ANCHOR[:10])
        for figure in ("spot", "forward", "discount", "forward_method"):
            assert header[figure] == table[figure], f"{figure} disagrees at {moment}"

        rows = {row["strike"]: row for row in table["rows"]}
        assert header["atm_iv"] == rows[header["atm_strike"]]["iv"]


def test_the_summary_is_strict_about_its_pair_exactly_as_the_chain_is(client):
    """Same keys, same rules.

    `/summary` and `/chain` are read for one screen at one minute, so a pair one of them
    refuses and the other quietly substitutes would put a header from one day above a
    table from another.

    Three refusals, and they are the Chain's own three: a date the store does not hold is
    a 404 naming it, an Expiry that date did not trade is a 404 naming what it did, and
    text that is not an Expiry label is a 422 because nothing was looked up.
    """
    missing = client.get("/summary", params={"moment": ANCHOR, "date": "2026-03-16"})
    assert missing.status_code == 404, missing.text
    assert "2026-03-16" in missing.json()["detail"]

    mispaired = client.get(
        "/summary", params={"moment": ANCHOR, "date": ANCHOR[:10], "expiry": "10MAR26"}
    )
    assert mispaired.status_code == 404, mispaired.text
    assert EXPIRY in mispaired.json()["detail"], "say what would have worked"

    unreadable = client.get("/summary", params={"moment": ANCHOR, "expiry": "2026-02-10"})
    assert unreadable.status_code == 422, unreadable.text
    assert EXPIRY in unreadable.json()["detail"], "say what the form is"


def test_a_moment_between_stops_answers_with_the_minute_before_it(client):
    """As-of, exactly as the Chain is.

    The time control only ever hands over a stop, but a hand-edited link can name any
    second of the day, and a header that refused would be stricter than the table beside
    it for no reason a trader could see.

    The `moment` that comes back is the one that was **asked for**, not the minute that
    answered - which is `ChainResponse`'s rule, and the two have to be the same rule or a
    client comparing what it sent against what it got finds them unequal on one endpoint
    only. Both spell it back through `datetime.isoformat`, so a fractional second comes
    back padded; what matters is that they pad it identically.
    """
    between = f"{ANCHOR}.5"
    header = summary_at(client, between, ANCHOR[:10])
    table = chain_at(client, between, ANCHOR[:10])

    assert header["moment"] == table["moment"], "one spelling of a moment, on both"
    assert header["moment"] != ANCHOR, "the moment asked for, not the minute that answered"
    assert header["spot"] == table["spot"] == summary_at(client, ANCHOR, ANCHOR[:10])["spot"]

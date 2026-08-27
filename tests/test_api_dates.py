"""Seam one, widened again: a day other than the anchor.

#67 derives, stores and serves every trading date in the dataset, so a trader reaches
one by naming it. The dropdown that makes that discoverable is #68; this file grades the
part that has to exist first, and it grades it where a trader meets it - over HTTP,
importing nothing from the modules it exercises, as the rest of this neighbourhood does.

Three dates, chosen for the ways they differ rather than to sample the twenty-four.
`tests/conftest.py` builds exactly these and says why.

| `2026-01-07` | the sparse end: 12 strikes over 150 minutes, most of them opening late |
| `2026-01-27` | the dense anchor, whose every served figure must be unchanged         |
| `2026-02-10` | Expiry, where the trading-day clock reaches zero                      |

Timestamps here are UTC; add 5h30m to read one as a trader would. The session runs 03:45
to 10:00 UTC, which is 09:15 to 15:30 IST.
"""

import pytest
from fastapi.testclient import TestClient

from payoff.api import app

SPARSE = "2026-01-07"
ANCHOR = "2026-01-27"
EXPIRY = "2026-02-10"


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def chain_at(client: TestClient, moment: str, date: str | None = None) -> dict:
    params = {"moment": moment} if date is None else {"moment": moment, "date": date}
    response = client.get("/chain", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_naming_the_anchor_serves_exactly_what_naming_nothing_serves(client):
    """The acceptance criterion the whole ticket is measured against: the anchor did not
    move.

    `date` is a new parameter and the anchor was reachable without it, so the first thing
    it must not do is mean something slightly different. Equality on the **whole
    response**, not on a field or two - a difference anywhere in ninety-four rows of
    quotes, ages, deltas and volatilities would show up here and nowhere else.

    The figures themselves are asserted in `test_api_chain.py`, unchanged, which is the
    other half of the same claim: those assertions were written against a chain derived
    from a committed seed and now pass against one derived from the raw files.
    """
    assert chain_at(client, "2026-01-27T06:30:00") == chain_at(
        client, "2026-01-27T06:30:00", ANCHOR
    )


def test_the_date_is_taken_off_the_moment_when_a_caller_names_none(client):
    """A moment already carries a date, and the two are never allowed to disagree.

    The session runs 03:45 to 10:00 UTC, so it never crosses a midnight and the trading
    date is the same in IST and UTC. That is what lets the parameter be optional - and
    what makes a client that only ever changes the moment still land on the right day.
    """
    implied = chain_at(client, "2026-02-10T06:30:00")
    named = chain_at(client, "2026-02-10T06:30:00", EXPIRY)

    assert implied == named
    assert implied["moment"] == "2026-02-10T06:30:00"
    assert implied["spot"] != chain_at(client, "2026-01-27T06:30:00")["spot"]


def test_a_sparse_day_is_thin_and_says_so_rather_than_borrowing_from_a_thick_one(client):
    """#67: the sparse end of the dataset, graded apart from the dense end.

    7 January quotes **12 strikes across 150 minutes** against the anchor's 94 across
    376 - a session that opened at 09:15 IST and stopped quoting at 15:29. Almost every
    failure mode of a generalised build hides here rather than in a liquid day: a
    partition filter that leaked would serve the anchor's 94 strikes under this date, a
    session window one bar out would change the count, and a clock counted from the first
    bar rather than from the open would move every volatility on the day.

    The date sits ten sessions further from Expiry than the anchor, which is the cheapest
    available proof that the clock was rebuilt per date rather than copied.
    """
    thin = chain_at(client, "2026-01-07T09:59:00", SPARSE)
    thick = chain_at(client, "2026-01-27T06:30:00", ANCHOR)

    assert len(thin["rows"]) == 12, "every strike that traded on the day, and no more"
    assert len(thick["rows"]) > 80

    strikes = [row["strike"] for row in thin["rows"]]
    assert strikes == sorted(strikes)
    assert min(strikes) >= 25_000, "this day traded high, nowhere near the anchor's wings"

    assert thin["expiry"] == thick["expiry"] == "10FEB26", "one series, twenty-four dates"
    assert thin["forward"] > 0.0
    assert thin["forward_method"] in {"parity_fit", "single_strike_parity", "spot"}


def test_a_strike_is_not_carried_forward_from_before_its_first_trade(client):
    """#67, and the one thing a carry-forward can get wrong that still looks right.

    The stored Chain holds every minute for every strike, so the obvious implementation
    fills the whole grid - and a strike that first traded at 13:44 then acquires a quote
    at 09:15, four and a half hours before anyone quoted it. Nothing on screen objects:
    it is a plausible price at a plausible strike, and it would sit in the chain all
    morning being wrong.

    27,000 CE on 7 January is the case, and it is a real one rather than a constructed
    one: its first bar of the day is at 08:14 UTC, four and a half hours into a
    fourteen-strike session.
    """
    before = chain_at(client, "2026-01-07T08:13:00", SPARSE)
    assert not [row for row in before["rows"] if row["strike"] == 27_000.0 and row["call"]]

    after = chain_at(client, "2026-01-07T08:14:00", SPARSE)
    quote = next(row for row in after["rows"] if row["strike"] == 27_000.0)["call"]
    assert quote is not None
    assert quote["age_minutes"] == 0, "its own bar, not one carried into the minute"

    # And a minute later it is carried, which is what the fill is for.
    carried = chain_at(client, "2026-01-07T08:15:00", SPARSE)
    later = next(row for row in carried["rows"] if row["strike"] == 27_000.0)["call"]
    assert later["age_minutes"] == 1
    assert later["last"] == quote["last"]


def test_the_first_minute_of_a_day_carries_only_what_traded_in_it(client):
    """The same claim at the edge where it is easiest to get wrong by one row.

    At the opening minute nothing has traded yet except what is trading now, so the
    filled chain and the quoted chain are the same thing. A fill that reached back across
    the overnight gap - into the previous session, which is a different partition - would
    show up here as a chain that is too wide at 09:15.
    """
    opening = chain_at(client, "2026-01-07T03:45:00", SPARSE)

    ages = [
        opening["rows"][at][side]["age_minutes"]
        for at in range(len(opening["rows"]))
        for side in ("call", "put")
        if opening["rows"][at][side]
    ]
    assert ages, "something traded in the opening minute"
    assert set(ages) == {0}, "nothing can be older than the day itself"


def test_expiry_day_reaches_a_time_to_expiry_of_zero_and_still_serves(client):
    """#67: "the Expiry date itself, where time to Expiry reaches zero".

    `dte_days` runs from 1.0 at the open of 10 February to exactly **0.0** at the final
    bar, and that last minute is the one place in the dataset where `T = 0`. Three things
    are undefined there and each is handled rather than avoided:

    - the parity **fit**, which needs `T` to turn a slope into a rate, falls to a lower
      tier of the ladder rather than returning a NaN;
    - the **volatility**, because the price stops depending on it - so the strikes that
      printed in that minute carry `null`, which is what `ChainRow.iv` is nullable for;
    - the **Greeks**, which `pricing.black76_greeks` refuses to compute at Expiry and is
      right to. Delta survives as the slope of the Expiry line: 1 above the Forward, 0
      below, and a put one less than its call.

    Vendor Greeks stop at 15:29 on this date. This engine serves 15:30.
    """
    close = chain_at(client, "2026-02-10T10:00:00", EXPIRY)
    assert len(close["rows"]) == 98, "the minute is served, and it is the whole chain"

    forward = close["forward"]
    for row in close["rows"]:
        if row["call"] and row["put"]:
            assert row["call"]["delta"] - row["put"]["delta"] == pytest.approx(1.0, abs=1e-12)
        if row["call"]:
            assert row["call"]["delta"] == (1.0 if forward > row["strike"] else 0.0)
        if row["put"]:
            assert row["put"]["delta"] == (0.0 if forward > row["strike"] else -1.0)

    # The volatility goes the other way: a strike whose freshest print lands in this
    # minute loses the one it had, because an expired price implies nothing. A strike
    # that last printed earlier keeps its own, inverted in its own minute, which is why
    # the chain is not blank.
    before = {row["strike"] for row in chain_at(client, "2026-02-10T09:59:00", EXPIRY)["rows"]
              if row["iv"] is None}
    after = {row["strike"] for row in close["rows"] if row["iv"] is None}
    assert before < after, "T = 0 takes volatilities away and never adds one"

    ages = {
        row["strike"]: min(row[side]["age_minutes"] for side in ("call", "put") if row[side])
        for row in close["rows"]
    }
    assert all(ages[strike] == 0 for strike in after - before), "only what printed at Expiry"
    assert len([row for row in close["rows"] if row["iv"] is not None]) > 80


def test_the_minute_before_expiry_is_an_ordinary_minute(client):
    """The control for the test above: `T = 0` is one minute wide, not a regime.

    At 09:59 UTC the clock reads 1/375 of a session - the smallest positive `T` in the
    dataset, a hundred times smaller than anything the solver was tuned on. Vega collapses
    there and Newton cannot take a first step from a flat seed of 0.20, which is what
    `pricing.implied_vol`'s bisection fallback exists for; without it this minute would
    carry almost no volatilities and this assertion is what would say so.

    The volatilities themselves reach 4.96, which is not a runaway. `sigma * sqrt(T)` is
    what a price actually sees, and at one minute to Expiry that is 0.016 - an ordinary
    number wearing an alarming annualisation.
    """
    almost = chain_at(client, "2026-02-10T09:59:00", EXPIRY)

    volatilities = [row["iv"] for row in almost["rows"] if row["iv"] is not None]
    assert len(volatilities) > 80, "a real chain, not a scattering of nulls"
    assert all(0.0 < value < 5.0 for value in volatilities)

    for row in almost["rows"]:
        for side in ("call", "put"):
            if not row[side]:
                continue
            # The two nullables move together, always: a delta is priced at the strike's
            # volatility, so there is no honest delta where there is no volatility.
            assert (row[side]["delta"] is None) == (row["iv"] is None), row["strike"]
            if row["iv"] is None:
                continue
            bound = (0.0, 1.0) if side == "call" else (-1.0, 0.0)
            assert bound[0] <= row[side]["delta"] <= bound[1]


def test_every_moment_of_a_built_date_is_one_the_chain_answers_on(client):
    """Spot-checked at both ends of two days rather than swept across 526 minutes.

    The failure this guards is a **partition** mismatch - a date filter that reaches the
    reader in one spelling and the tree in another - and that breaks at the first minute
    of a day, not at the four-hundredth.
    """
    for date, first, last in (
        (SPARSE, "2026-01-07T03:45:00", "2026-01-07T09:59:00"),
        (EXPIRY, "2026-02-10T03:45:00", "2026-02-10T10:00:00"),
    ):
        for moment in (first, last):
            served = chain_at(client, moment, date)
            assert served["moment"] == moment
            assert served["rows"]

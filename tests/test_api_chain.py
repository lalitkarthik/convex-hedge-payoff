"""Seam one again: the Chain endpoint.

The Chain a trader browses, asserted where a trader meets it. As in
`test_api_analyse.py` these tests never import `chain` or `strategy` - what is graded
is what comes back over HTTP.

The anchor moment is **2026-01-27 06:30 UTC = 12:00 IST**, the same minute #24's
straddle was measured at. Add 5h30m to read any timestamp here as a trader would.
"""

import pytest
from fastapi.testclient import TestClient

from payoff.api import app

MOMENT = "2026-01-27T06:30:00"


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="module")
def chain(client: TestClient) -> dict:
    response = client.get("/chain", params={"moment": MOMENT})
    assert response.status_code == 200, response.text
    return response.json()


def test_the_as_of_view_quotes_at_least_41_strikes_on_both_sides(chain):
    """#28's headline number, and the entire justification for serving as-of.

    Only strikes that actually traded in a given minute have a bar. Read strictly, "the
    Chain at 06:30" is **9 strikes quoting both sides** - a scattering of rows, not a
    chain, and on some minutes of this day it is zero. Serving each strike's last known
    quote at or before the moment gives **41**.

    Measured on the committed sample at the anchor minute, so this number moves only if
    the data or the as-of rule changes.
    """
    both_sided = [row for row in chain["rows"] if row["call"] and row["put"]]
    assert len(both_sided) >= 41


def test_each_quote_carries_what_a_trader_judges_liquidity_by(chain):
    """Stories 3 and 4: last traded price, open interest, volume and delta.

    Delta is on the quote rather than the row because it is genuinely per side - a call
    and its put at one strike have deltas one apart, not equal. That is the opposite of
    implied volatility, and the two are easy to conflate.
    """
    quoted = [row[side] for row in chain["rows"] for side in ("call", "put") if row[side]]
    assert len(quoted) > 100, "the sample day is liquid: 94 strikes, most quoted"

    for quote in quoted:
        assert {"last", "open_interest", "volume", "delta"} <= set(quote)
        assert quote["last"] > 0
        assert quote["open_interest"] >= 0
        assert quote["volume"] >= 0

    calls = [row["call"]["delta"] for row in chain["rows"] if row["call"]]
    puts = [row["put"]["delta"] for row in chain["rows"] if row["put"]]
    assert all(0.0 <= delta <= 1.0 for delta in calls), "a call's delta is positive"
    assert all(-1.0 <= delta <= 0.0 for delta in puts), "a put's is negative"


def test_every_quote_carries_the_age_of_its_bar_in_whole_minutes(chain):
    """#28 carries the age; **#31 does the dimming** - but emit it here or #31 lands
    with nothing to render.

    This is the honesty requirement. On the sample day the median quote is one minute
    old while the wings reach two and a half hours, and presenting a 153-minute-old
    price as live would be dishonest rather than merely imprecise. A quote is never
    from the future, so the age is never negative, and bars are one minute wide, so it
    is a whole number.
    """
    ages = [
        row[side]["age_minutes"]
        for row in chain["rows"]
        for side in ("call", "put")
        if row[side]
    ]

    assert all(isinstance(age, int) for age in ages), "bars are one minute wide"
    assert min(ages) == 0, "something traded in the anchor minute itself"
    assert max(ages) > 120, "and the wings are hours old - the field is real, not a constant"


def test_implied_volatility_belongs_to_the_strike_and_not_to_either_side(chain):
    """#28: "**one shared implied volatility column between them** - because implied
    volatility is a property of the strike, not of the Leg."

    The acceptance criterion phrases this as "the call and put rows at a given strike
    carry **equal** implied volatility", and served as-of that phrasing cannot hold.
    Measured at the anchor minute: of the 41 both-sided strikes, only the **9** whose
    two sides traded in the same minute quote the same volatility. The other **32**
    differ - by up to **0.0275** at the 23500 strike, which quotes 0.1861 against
    0.2136 because the two sides are minutes apart.

    Restricting the view to a single minute would make the two equal and cost 32 of the
    41 strikes, which is the whole point of serving as-of. So the endpoint publishes
    **one volatility per strike** and none per side: a single number cannot disagree
    with itself, which is a stronger guarantee than two numbers that happen to match.
    """
    both_sided = [row for row in chain["rows"] if row["call"] and row["put"]]
    assert both_sided

    for row in both_sided:
        assert row["iv"] is not None
        assert "iv" not in row["call"]
        assert "iv" not in row["put"]
        assert 0.0 < row["iv"] < 1.0, "a decimal, never a percentage"


def test_the_header_shows_spot_and_one_fixed_expiry_and_nothing_invented(chain):
    """Stories 9 and 10 - and nothing this dataset does not contain.

    No futures price, no volatility index, no implied-volatility percentile. None of
    the three exists in the data, and a fabricated one beside honest numbers is worse
    than an omitted one. CONTEXT.md goes further on the first: a futures price is
    deliberately not a term in this project, because no futures series exists and using
    the word would be an assumption dressed as an observation.

    There is exactly one Expiry in the file, which is why this is text rather than a
    dropdown - and why calendars and diagonals are unbuildable here rather than merely
    deprioritised.
    """
    assert chain["spot"] == pytest.approx(25100.25), "the NIFTY level at the anchor minute"
    assert chain["expiry"] == "10FEB26"

    invented = {"futures_price", "futures", "vix", "iv_percentile", "volatility_index"}
    assert not invented & set(chain)


def test_strikes_come_back_in_order(chain):
    """Ninety-odd strikes down the middle only read as a chain if they are sorted."""
    strikes = [row["strike"] for row in chain["rows"]]
    assert strikes == sorted(strikes)
    assert len(strikes) > 80, "the sample day quotes 94 strikes"


def test_a_leg_can_be_held_more_than_once(client):
    """Story 14: ratio spreads need a Quantity, not four copies of the same Leg.

    Quantity scales what the Leg contributes and nothing else. In particular it cannot
    move a Breakeven: scaling multiplies the whole curve, and multiplying cannot move a
    zero. That is the same property #29 asserts of Lot Size, one level down.
    """

    def straddle(quantity: int) -> dict:
        return client.post(
            "/analyse",
            json={
                "moment": MOMENT,
                "legs": [
                    {"strike": 25200.0, "option_type": ot, "direction": -1, "quantity": quantity}
                    for ot in ("CE", "PE")
                ],
            },
        ).json()["metrics"]

    once, twice = straddle(1), straddle(2)

    assert twice["max_profit"] == pytest.approx(2 * once["max_profit"], abs=1e-9)
    assert twice["net_premium"] == pytest.approx(2 * once["net_premium"], abs=1e-9)
    assert twice["breakevens"] == pytest.approx(once["breakevens"], abs=1e-9)
    assert twice["max_profit"] == pytest.approx(1341.5, abs=1e-6), "670.75 twice over"

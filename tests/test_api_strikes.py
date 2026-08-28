"""What a caller sees when a strike cannot be priced.

Every other error path at this boundary already answers with a status and a `detail`:
an unknown Preset is a 404, an unstored series is a 404, a Strategy spanning two
Expiries is a 422. A strike that is not quoted was the gap - it raised
`StrikeNotQuoted`, nothing caught it, and FastAPI turned it into a 500 with no body.

A 500 says the server broke. It did not: the trader asked for an instrument that has no
price at that minute, which is an answer, and one the interface can act on. The
distinction is `test_api_presets.py`'s, made there about a Preset name and holding here
for the same reason.

**This is reachable without any new interface.** Build a Strategy at 06:30, drag the
time control back to 03:45, and a strike that had not yet printed becomes a 500 - the
quoted set is per-minute and per-side, and it grows through the session:

    03:45   56 strikes,  10 quoting both sides
    06:30   91 strikes,  41 quoting both sides
    10:00   94 strikes,  92 quoting both sides

The anchor throughout is 2026-01-27 06:30 UTC = 12:00 IST.
"""

import pytest
from fastapi.testclient import TestClient

from payoff.api import app

MOMENT = "2026-01-27T06:30:00"
EXPIRY = "10FEB26"

QUOTED = 25200.0
"""Quoted on both sides at the anchor. The control: every test below changes one thing
about a Leg that is known to work."""


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def analyse(client: TestClient, legs: list[dict], moment: str = MOMENT):
    body = [{"expiry": EXPIRY, **leg} for leg in legs]
    return client.post("/analyse", json={"moment": moment, "legs": body})


def test_the_control_leg_is_priced(client):
    """If this fails, nothing below is evidence of anything."""
    response = analyse(client, [{"strike": QUOTED, "option_type": "CE", "direction": 1}])
    assert response.status_code == 200, response.text


def test_a_strike_off_the_grid_is_not_found(client):
    """Strikes are 50 apart. 25201 is not a strike, it is a typo or a bad slider."""
    response = analyse(client, [{"strike": 25201.0, "option_type": "CE", "direction": 1}])

    assert response.status_code == 404, response.text
    assert "25201" in response.json()["detail"], "the reply must name the strike refused"


def test_a_strike_outside_the_days_range_is_not_found(client):
    """The day spans 23,300 to 27,950. Nothing is quoted at 99,999 and nothing can be."""
    response = analyse(client, [{"strike": 99999.0, "option_type": "CE", "direction": 1}])

    assert response.status_code == 404, response.text


def test_a_strike_quoted_only_on_the_other_side_is_not_found(client):
    """The case a min/max/step slider walks straight into.

    23,300 is a real strike, inside the day's range, on the 50-point grid, and present
    in the Chain at this minute - and it has traded only as a put. Every check short of
    asking for the call itself says this Leg is fine. `resolve_legs` keys on
    `(strike, option_type)`, and 50 of the anchor's 91 strikes quote one side only, so
    this is the common case rather than the exotic one.
    """
    put = analyse(client, [{"strike": 23300.0, "option_type": "PE", "direction": 1}])
    assert put.status_code == 200, "the put half is quoted; the premise depends on it"

    call = analyse(client, [{"strike": 23300.0, "option_type": "CE", "direction": 1}])
    assert call.status_code == 404, call.text
    assert "23300" in call.json()["detail"]
    assert "CE" in call.json()["detail"], "which side was asked for is half the reason"


def test_every_refusal_carries_a_detail(client):
    """The shape the client reads.

    `web/lib/api.ts` surfaces `detail` and shows it to the trader. A 500 arrives with an
    empty one, which is how this presented before it was fixed: a blank message.
    """
    for leg in (
        {"strike": 25201.0, "option_type": "CE", "direction": 1},
        {"strike": 99999.0, "option_type": "PE", "direction": 1},
    ):
        body = analyse(client, [leg]).json()
        assert isinstance(body.get("detail"), str) and body["detail"], body


def test_one_unquoted_leg_refuses_the_whole_strategy(client):
    """Not a partial answer.

    The same rule the frontend's link parser follows: a Strategy that is three-quarters
    readable is not three-quarters analysable, and a chart of the legs that did resolve
    would be a chart of a position nobody holds.
    """
    response = analyse(
        client,
        [
            {"strike": QUOTED, "option_type": "CE", "direction": 1},
            {"strike": 25201.0, "option_type": "PE", "direction": 1},
        ],
    )

    assert response.status_code == 404, response.text
    assert "curve" not in response.json()


def test_the_entry_premium_override_still_works(client):
    """The regression guard for the frontend's half of this change.

    A slider that moves a strike must *drop* `entry_premium`, because the server cannot
    tell a stale one carried over from the old strike from a deliberate "what if I had
    entered at X" - both arrive as a bare float. That rule lives in the client, so what
    is asserted here is the thing it depends on: absent means read the Chain, present
    means honour it, and neither meaning has moved.
    """
    quoted = analyse(client, [{"strike": QUOTED, "option_type": "CE", "direction": 1}])
    assert quoted.json()["metrics"]["breakevens"] == pytest.approx([25544.05]), "25200 + 344.05"

    overridden = analyse(
        client,
        [{"strike": QUOTED, "option_type": "CE", "direction": 1, "entry_premium": 100.0}],
    )
    assert overridden.json()["metrics"]["breakevens"] == pytest.approx([25300.0]), "25200 + 100"


def test_a_strike_with_no_volatility_is_unprocessable_rather_than_missing(client):
    """Quoted, and still unpriceable - a different answer from a different cause.

    In the last minute of Expiry day the price stops depending on volatility, and 14 of
    the 98 strikes quoted at 10:00 carry none. Nothing is missing here: the instrument
    is in the Chain with a last traded price. It is the model that has no answer, so
    this is a 422 and not a 404, and a client that hid the strike on this reply would be
    hiding something the trader can plainly see on the Chain.
    """
    last_minute = "2026-02-10T10:00:00"
    response = analyse(
        client,
        [{"strike": 23250.0, "option_type": "PE", "direction": 1}],
        moment=last_minute,
    )

    assert response.status_code == 422, response.text
    assert "volatility" in response.json()["detail"]


def test_the_two_refusals_are_told_apart(client):
    """The one assertion that would catch a handler registered too broadly.

    `NotPriceable` subclasses `ValueError`; had the handler been registered on
    `ValueError` itself it would still pass every test above, while quietly reporting
    any bug in the engine as a fault in the request. These two must not collapse.
    """
    absent = analyse(client, [{"strike": 25201.0, "option_type": "CE", "direction": 1}])
    present_but_unpriceable = analyse(
        client,
        [{"strike": 23250.0, "option_type": "PE", "direction": 1}],
        moment="2026-02-10T10:00:00",
    )

    assert absent.status_code == 404
    assert present_but_unpriceable.status_code == 422


@pytest.mark.parametrize("option_type, side", [("CE", "call"), ("PE", "put")])
def test_the_chain_predicts_exactly_what_analyse_will_accept(client, option_type, side):
    """The contract the strike slider is built on, asserted as a set equality.

    `web/lib/strikes.ts` builds the ladder the trader drags along by filtering the Chain
    on two conditions - the side is quoted, and the strike carries an implied volatility
    - because those are the two `resolve_legs` applies. So **the set of strikes the
    interface offers and the set the engine can price must be the same set**, and that
    equality is what makes the slider unable to produce a refusal.

    Both directions matter. Offering a strike that will not price is a dead end the
    trader was invited to walk into; withholding one that would have priced silently
    hides a tradable instrument. Neither is visible from the frontend alone, which is
    why the assertion lives here, against the engine that decides.

    At the anchor this is 68 strikes offered of 91 for calls, and 64 of 91 for puts.
    """
    rows = client.get("/chain", params={"moment": MOMENT}).json()["rows"]

    offered = {r["strike"] for r in rows if r["iv"] is not None and r[side] is not None}
    withheld = {r["strike"] for r in rows} - offered
    assert offered and withheld, "a minute that offered everything would prove nothing"

    def prices(strike: float) -> bool:
        leg = {"strike": strike, "option_type": option_type, "direction": 1}
        return analyse(client, [leg]).status_code == 200

    assert {k for k in offered if not prices(k)} == set(), "offered a strike that will not price"
    assert {k for k in withheld if prices(k)} == set(), "withheld a strike that would have priced"

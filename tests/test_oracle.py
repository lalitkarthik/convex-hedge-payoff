"""Seam two: the pricing core, tested against the Oracle.

**This is the one test that matters.** Everything else in this project guards against
regression; this one guards against self-deception. It converts "the chart looks right"
into "the model reproduces tens of thousands of independently-computed Greeks", and it
is the reason the engine reimplements Black-76 instead of importing it.

#23 gives this module a seam of its own for exactly one reason: the assertion is tens
of thousands of numbers, and routing it through JSON would test serialisation instead
of mathematics. Nothing else belongs here - behaviour a trader can observe is asserted
at the HTTP boundary.

The Oracle is `Data/sample/chain_2026-01-27.parquet`: 23,581 rows carrying the pre-solved
volatility and Greeks alongside the Forward and Discount Factor that produced them. It is
a **test fixture, never an input** (CONTEXT.md). If the engine ever reads it to produce an
answer, the point of the project has been lost.
"""

import inspect
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from payoff import pricing
from payoff.pricing import (
    TRADING_DAYS_PER_YEAR,
    black76_greeks,
    black76_price,
    implied_vol,
)

SAMPLE = Path(__file__).resolve().parents[1] / "Data" / "sample" / "chain_2026-01-27.parquet"
"""The Oracle. A test fixture, never an input (CONTEXT.md)."""

DISCOUNT = 0.997167
"""A discount factor off the sample: 10 trading days from expiry."""


def test_at_expiry_an_option_is_worth_its_discounted_intrinsic_value():
    """#26: 'a time to Expiry of zero is valid and returns the discounted intrinsic
    value'.

    T = 0 is the Expiry line, not an error and not a division by zero. It is the case
    the payoff chart's green line is made of, so a core that raised here would push the
    Expiry curve into a special path that nothing verifies.
    """
    in_the_money = black76_price(25500.0, 25200.0, 0.0, 0.18, DISCOUNT, is_call=True)
    assert in_the_money == pytest.approx(299.1501, abs=1e-9), "300 in the money, discounted"

    put = black76_price(24900.0, 25200.0, 0.0, 0.18, DISCOUNT, is_call=False)
    assert put == pytest.approx(299.1501, abs=1e-9)

    worthless = black76_price(24900.0, 25200.0, 0.0, 0.18, DISCOUNT, is_call=True)
    assert worthless == pytest.approx(0.0, abs=1e-12)


@pytest.fixture(scope="module")
def oracle() -> pd.DataFrame:
    """The committed sample: 23,581 rows of pre-solved volatility and Greeks.

    Every row carries the Forward and the Discount Factor that produced its Greeks, so
    the core is fed exactly what it wants with no conversion in between. A failure here
    means the mathematics is wrong, not the plumbing (ADR-0001).
    """
    rows = pd.read_parquet(SAMPLE)
    assert len(rows) == 23581, "the committed sample changed size"
    return rows


def test_a_call_and_a_put_at_one_strike_differ_by_the_discounted_basis(oracle):
    """Put-call parity: C - P = D x (F - K), on all 23,581 rows at once.

    An identity that holds for any correct Black-76 and for no incorrect one - a
    swapped sign in d2, or a cumulative normal read the wrong way round, breaks it.
    It is checked before the Greeks because it grades the price function itself, and
    the Oracle ships no price column to grade it against. #26 forbids the obvious
    substitute: never assert the model price equals the last traded price, which holds
    for 100% of out-of-the-money rows and only 6.2% of in-the-money ones, because
    in-the-money prints go stale.
    """
    T = oracle.dte_days.to_numpy() / TRADING_DAYS_PER_YEAR
    forward, strike = oracle.forward.to_numpy(), oracle.strike.to_numpy()
    discount, vol = oracle.discount.to_numpy(), oracle.iv.to_numpy()

    call = black76_price(forward, strike, T, vol, discount, is_call=True)
    put = black76_price(forward, strike, T, vol, discount, is_call=False)

    parity = discount * (forward - strike)
    assert np.abs((call - put) - parity).max() < 1e-9


def test_before_expiry_every_option_carries_time_value(oracle):
    """Ten trading days from Expiry, no option is worth only its intrinsic value.

    Parity alone cannot catch a core that returns discounted intrinsic value at every
    T - the identity holds for that too. This is what separates the Expiry line from a
    live price: with time left and a positive volatility, the excess over intrinsic is
    strictly positive on all 23,581 rows.
    """
    T = oracle.dte_days.to_numpy() / TRADING_DAYS_PER_YEAR
    forward, strike = oracle.forward.to_numpy(), oracle.strike.to_numpy()
    discount, vol = oracle.discount.to_numpy(), oracle.iv.to_numpy()

    for is_call in (True, False):
        live = black76_price(forward, strike, T, vol, discount, is_call=is_call)
        at_expiry = black76_price(forward, strike, 0.0, vol, discount, is_call=is_call)
        assert (live - at_expiry).min() > 0.0


GREEKS = ("delta", "gamma", "vega", "theta", "rho")
"""The five the Oracle ships and #26 grades. Vanna, volga and charm are in the file and
are deliberately not asserted - nothing in v1 computes them."""

DISCOUNTED = ("delta", "gamma")
"""The two whose convention this engine does not share with the Oracle (#53).

The Black-76 price is `D[F N(d1) - K N(d2)]`, so every derivative of it inherits the D.
The file reports `N(d1)`; we report `D N(d1)`. `docs/calculations.md` left the choice to
#27 and #53 settled it: a delta of exactly 1 would mean an undiscounted payoff, and this
payoff is discounted."""

TOLERANCE = 1e-6
"""#26's figure. The measured drift is orders of magnitude below it, so this is a
tripwire for a changed model rather than a tuned threshold."""


def drift_against_the_oracle(oracle: pd.DataFrame) -> dict[str, float]:
    """Worst absolute disagreement per Greek, over every row of the sample.

    Split by option type only because `is_call` is a property of the contract, not of
    the row: two vectorised calls cover all 23,581 rows, and neither loops.
    """
    worst = dict.fromkeys(GREEKS, 0.0)
    for option_type in ("CE", "PE"):
        rows = oracle[oracle.option_type == option_type]
        discount = rows.discount.to_numpy()
        mine = black76_greeks(
            rows.forward.to_numpy(),
            rows.strike.to_numpy(),
            rows.dte_days.to_numpy() / TRADING_DAYS_PER_YEAR,
            rows.iv.to_numpy(),
            discount,
            is_call=option_type == "CE",
        )
        for greek in GREEKS:
            # Delta and gamma are DISCOUNTED here and undiscounted in the file (#53), so
            # the Oracle is scaled up to this convention rather than ours scaled down to
            # it. The gap is exactly D - it reaches 1.77%, which is large enough to
            # matter and small enough to read as rounding.
            theirs = rows[greek].to_numpy()
            if greek in DISCOUNTED:
                theirs = theirs * discount
            worst[greek] = max(worst[greek], float(np.abs(mine[greek] - theirs).max()))
    return worst


def test_all_five_greeks_reproduce_the_oracle_on_every_row(oracle):
    """The assertion this project exists to make.

    Not a sample, not a tolerance chosen to make it pass: every one of the 23,581 rows,
    against Greeks that were computed independently of this code. The conventions are
    the Oracle's and several are not textbook - delta and gamma undiscounted, vega per
    volatility point, rho per one percent, and theta a one-trading-day repricing rather
    than the analytic formula. Writing the analytic theta fails here for a reason that
    looks like a bug and is not.

    Graded against the Greeks columns and never against `last`: implied volatility is
    one value per strike, inverted from the out-of-the-money Leg and shared with its
    in-the-money twin, so a model price and a last traded price legitimately disagree.
    """
    worst = drift_against_the_oracle(oracle)

    for greek, value in worst.items():
        assert value < TOLERANCE, f"{greek} drifts {value:.3e} from the oracle"


def test_arrays_go_in_and_results_of_the_same_shape_come_out(oracle):
    """#26 measured this rather than preferring it.

    A 400-point curve for four Legs costs 583.73 ms scalar against 2.78 ms vectorised,
    and the frame budget is 16.7 ms. A scalar core needs rewriting the first time
    anyone drags a control, so the entry points take arrays and return the same shape.

    No entry point returns a not-a-number on any row of the sample - ADR-0001 bans it
    in the core because a NaN renders as a silent gap in a payoff chart and survives
    review.
    """
    forward = oracle.forward.to_numpy()
    strike = oracle.strike.to_numpy()
    T = oracle.dte_days.to_numpy() / TRADING_DAYS_PER_YEAR
    vol, discount = oracle.iv.to_numpy(), oracle.discount.to_numpy()

    price = black76_price(forward, strike, T, vol, discount, is_call=True)
    assert price.shape == forward.shape
    assert not np.isnan(price).any()

    exposure = black76_greeks(forward, strike, T, vol, discount, is_call=True)
    for greek in GREEKS:
        assert exposure[greek].shape == forward.shape, greek
        assert not np.isnan(exposure[greek]).any(), greek


def test_where_the_maths_is_undefined_the_core_raises_instead_of_returning_a_nan():
    """#26: 'zero or negative volatility raises rather than returning a not-a-number'.

    A negative volatility is the dangerous one. It does not produce a NaN - it produced
    -86.41 for a call worth 299.10, a number that looks like a price, survives a chart
    and survives review. Raising is ADR-0001's instruction and the only outcome a
    caller cannot ignore.

    The Greeks at Expiry are the same rule from the other side: gamma divides by the
    volatility's time-scaling, which is zero once no time remains, and theta is the
    change over a session that no longer exists. The *price* at T = 0 is well defined
    and is the Expiry line; the exposures are not, and this is where the two part
    company.
    """
    for bad_vol in (0.0, -0.18):
        with pytest.raises(ValueError):
            black76_price(25500.0, 25200.0, 0.04, bad_vol, DISCOUNT, is_call=True)
        with pytest.raises(ValueError):
            black76_greeks(25500.0, 25200.0, 0.04, bad_vol, DISCOUNT, is_call=True)

    # One bad entry in an array is still a bad entry.
    with pytest.raises(ValueError):
        black76_price(
            np.array([25500.0, 25500.0]),
            25200.0,
            0.04,
            np.array([0.18, -0.01]),
            DISCOUNT,
            is_call=True,
        )

    with pytest.raises(ValueError):
        black76_greeks(25500.0, 25200.0, 0.0, 0.18, DISCOUNT, is_call=True)

    assert black76_price(25500.0, 25200.0, 0.0, 0.18, DISCOUNT, is_call=True) == pytest.approx(
        299.1501, abs=1e-9
    ), "the price at Expiry stays valid - it is the green line on the chart"


def test_implied_volatility_inverts_the_core_and_recovers_the_oracles_own_number(oracle):
    """#26: 'implied volatility solving lives with the pricing core, not with the
    Strategy layer'.

    It inverts this module's own function, so it belongs beside it: data flows down and
    the maths stays in the core. The Strategy layer calls it with the market prices it
    holds and never reimplements it.

    Graded by round trip against the Oracle's volatility, which was solved
    independently of this code: price at the Oracle's volatility, invert the price, and
    the number must come back. Note what is *not* asserted - that the model price
    equals `last`. That holds for every out-of-the-money row and 6.2% of in-the-money
    ones, because in-the-money prints go stale.
    """
    for option_type in ("CE", "PE"):
        rows = oracle[oracle.option_type == option_type]
        forward, strike = rows.forward.to_numpy(), rows.strike.to_numpy()
        T = rows.dte_days.to_numpy() / TRADING_DAYS_PER_YEAR
        discount, vol = rows.discount.to_numpy(), rows.iv.to_numpy()
        is_call = option_type == "CE"

        price = black76_price(forward, strike, T, vol, discount, is_call=is_call)
        recovered = implied_vol(price, forward, strike, T, discount, is_call=is_call)

        assert np.abs(recovered - vol).max() < 1e-6


def test_the_interface_takes_no_spot_no_rate_and_reads_no_data():
    """ADR-0001, asserted rather than trusted: `price(forward, strike, T, vol,
    discount, is_call)`.

    The payoff chart's x-axis is Spot, so the obvious signature takes one. It was
    rejected: a core accepting a Spot and a rate has to reconstruct the Forward
    internally, and the reconstruction is the unstable part - the implied continuous
    rate runs 0.9% to 28.4% and diverges as T approaches zero, and on 2,397 of 8,356
    minutes a Forward cannot be fitted at all. That contested rule (#13) lives above
    the seam where it can be argued about. This test is what stops it drifting back in.

    The core also reads nothing. The Oracle is a test fixture, never an input
    (CONTEXT.md) - if the engine ever read it to produce an answer, the point of the
    project would be lost, and the read would most plausibly appear right here.
    """
    for entry_point in (black76_price, black76_greeks):
        parameters = list(inspect.signature(entry_point).parameters)
        assert parameters[:5] == ["forward", "strike", "T", "vol", "discount"]
        assert not {"spot", "rate", "r", "S", "underlying"} & set(parameters)

    source = Path(pricing.__file__).read_text()
    assert "parquet" not in source
    assert "pandas" not in source

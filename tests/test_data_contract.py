"""Assertions about the shape of the data, not about the maths.

These lock in the findings from issues #2, #4 and #6 so that a bad regeneration
of the sample slice fails loudly instead of quietly changing every number
downstream. The maths itself is guarded by the golden-file test, which arrives
with `src/payoff/pricing.py` (issue #12, part b).

Everything here reads the 2.2 MB committed sample rather than the 43 MB of raw
parquet, so the suite stays fast enough to run on every push.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SAMPLE = Path(__file__).resolve().parents[1] / "Data" / "sample" / "chain_2026-01-27.parquet"


@pytest.fixture(scope="module")
def chain() -> pd.DataFrame:
    return pd.read_parquet(SAMPLE)


def test_sample_has_the_expected_shape(chain):
    assert len(chain) == 23_581
    assert set(chain.option_type.unique()) == {"CE", "PE"}
    for column in ("ts", "strike", "option_type", "last", "forward", "discount", "dte_days", "iv"):
        assert column in chain.columns


def test_strike_grid_is_uniformly_fifty(chain):
    """#4: all 97 gaps across the full chain are exactly 50, with no tightening near ATM."""
    strikes = np.sort(chain.strike.unique())
    assert set(np.diff(strikes)) == {50.0}


def test_every_price_is_a_multiple_of_the_tick(chain):
    """#4: the NIFTY option tick is 0.05, and 100% of observed prices respect it."""
    prices = pd.concat([chain.Open, chain.High, chain.Low, chain.Close, chain["last"]]).dropna()
    assert (np.round(prices * 100) % 5 == 0).all()


def test_iv_is_shared_between_a_call_and_its_put(chain):
    """#2: iv is one value per strike, inverted from the OTM leg and shared with its ITM twin.

    This is why the golden test must assert against the Greeks columns and never
    against `last`, and it is why the reference UI shows a single centred IV column.
    """
    pairs = chain.pivot_table(index=["ts", "strike"], columns="option_type", values="iv").dropna()
    assert len(pairs) > 4_000
    assert np.isclose(pairs.CE, pairs.PE).all()


def test_close_equals_the_greeks_last_price(chain):
    """#6: options.Close is identical to greeks.last on every row.

    If this ever fails, the IST/UTC join in scripts/build_sample.py has drifted -
    a naive join returns wrong or zero rows silently, which is the trap #6 documents.
    """
    assert (chain.Close == chain["last"]).all()


def test_one_session_consumes_exactly_one_day_of_the_trading_clock(chain):
    """#6: dte_days is a trading-time clock. One session is 1.0, and nothing decays overnight."""
    assert chain.dte_days.max() == pytest.approx(11.0)
    assert chain.dte_days.min() == pytest.approx(10.0)

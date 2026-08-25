"""Implied volatility, solved rather than read (#52).

`docs/calculations.md` section 4. The sample file carries an `iv` column and the engine
must not read it: `chain.load_chain()` drops it, and this file is the **only** place in
the tree where it is opened, on the right-hand side of a comparison.

Two seams, and the split matters. `pricing.implied_vol` is the maths - it receives
arrays and returns numbers, and is tested the way `test_oracle.py` tests the rest of
that module. `chain.solved_volatility` is the **rule**: which leg is inverted, and which
strike copies its answer from a twin. Grading the rule anywhere else would mean the test
re-deciding what the engine decides, and agreeing with itself.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from payoff import chain
from payoff.pricing import TRADING_DAYS_PER_YEAR, implied_vol

SAMPLE = Path(__file__).resolve().parents[1] / "Data" / "sample" / "chain_2026-01-27.parquet"

ANCHOR = "2026-01-27T06:30:00"
"""12:00 IST. Section 4 publishes its slice here: 46 out-of-the-money legs."""


@pytest.fixture(scope="module")
def sample() -> pd.DataFrame:
    return pd.read_parquet(SAMPLE)


def test_the_solver_reaches_the_answer_in_a_handful_of_sweeps(sample):
    """Section 4: the iteration ceiling is a real check, not decoration.

    It is what catches the vega divided by 100. `black76_greeks` returns vega per
    volatility *point*, and feeding that to Newton makes every step a hundred times too
    small - the solver still arrives, several hundred iterations later. That failure is
    invisible to an assertion on the answer and visible only to one on the count, which
    is why the ceiling is passed in rather than left at its default.

    Measured at the anchor: 5 sweeps for all 46 legs, seeded flat at 0.20.
    """
    snap = sample[sample.ts == pd.Timestamp(ANCHOR)]
    forward = snap.forward.to_numpy(float)
    strike = snap.strike.to_numpy(float)
    is_call = (snap.option_type == "CE").to_numpy()

    # The out-of-the-money leg, which is the only one section 4 inverts.
    otm = np.where(is_call, strike >= forward, strike < forward)
    legs = snap[otm]
    assert len(legs) == 46, "section 4's published slice"

    for call in (True, False):
        rows = legs[(legs.option_type == "CE") == call]
        sigma = implied_vol(
            rows["last"].to_numpy(float),
            rows.forward.to_numpy(float),
            rows.strike.to_numpy(float),
            rows.dte_days.to_numpy(float) / TRADING_DAYS_PER_YEAR,
            rows.discount.to_numpy(float),
            is_call=call,
            max_sweeps=10,
        )
        assert np.abs(sigma - rows.iv.to_numpy(float)).max() < 1e-9


def test_the_engine_recovers_the_sources_own_volatility_on_every_row(sample):
    """#52, the whole day: 23,581 rows, and the engine reads none of them.

    The rule is not "invert the out-of-the-money leg" alone - measured, that covers
    18,602 rows and is silent about the rest. What reproduces the column is three cases:

    | out of the money                       | 18,602 | inverted from its own `last`       |
    | in the money, twin quoted that minute  |  4,587 | **copied** from the twin           |
    | in the money, no twin that minute      |    392 | inverted from its own `last`       |

    The copy is exact - every one of those 4,587 carries a float identical to its twin's,
    bit for bit - and it is a convention rather than a necessity: only 5 of them sit
    below discounted intrinsic and so admit no volatility at all. The other 4,582 would
    solve, to a *different* number, because an in-the-money print goes stale.
    """
    solved = chain.solved_volatility()

    assert solved.index.names == ["ts", "strike"], "one volatility per strike, not per side"
    assert len(solved) == 18_994, "the strike-minutes with a quote to invert"

    source = sample.set_index(["ts", "strike"]).iv
    assert np.abs(solved.reindex(source.index).to_numpy() - source.to_numpy()).max() < 1e-9

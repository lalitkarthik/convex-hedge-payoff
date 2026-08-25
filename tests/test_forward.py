"""The Forward and the Discount Factor, derived from the option prices (#51).

`CONTEXT.md:138` - "If the engine ever reads the Oracle to produce an answer, the point
of the project has been lost." Both quantities exist as columns in the sample file and
the engine must not read either. It fits them instead, and this file is the **only**
place in the tree where those columns are opened, on the right-hand side of a comparison.

Tested the way `test_oracle.py` tests `pricing.py`: the slicing happens here, and the
module under test receives arrays and returns numbers. Everything a client can see -
the chain's forward, the at-the-money strike that moves with it - is asserted over HTTP
in `test_api_chain.py` and `test_api_presets.py`, as the rest of the suite is.
"""

import inspect
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from payoff import forward
from payoff.pricing import TRADING_DAYS_PER_YEAR

SAMPLE = Path(__file__).resolve().parents[1] / "Data" / "sample" / "chain_2026-01-27.parquet"

ANCHOR = "2026-01-27T06:30:00"
"""12:00 IST. Every published figure in `docs/calculations.md` section 1 is measured here."""

# One real minute per route through the ladder. Named rather than searched for, so a
# regression names the minute it broke on.
PARITY_VIA_TOO_FEW_PAIRS = "2026-01-27T06:38:00"       # 4 paired strikes
PARITY_VIA_DISCOUNT_ABOVE_ONE = "2026-01-27T03:45:00"  # 10 pairs, slope gives D > 1
PARITY_VIA_RATE_TOO_HIGH = "2026-01-27T03:46:00"       # 14 pairs, implied rate >= 30%
SPOT_VIA_UNPAIRED_ATM = "2026-01-27T06:41:00"          # 3 pairs, none at the money
SPOT_VIA_NO_PAIRS_AT_ALL = "2026-01-27T10:00:00"       # the close: nothing quotes both sides


@pytest.fixture(scope="module")
def sample() -> pd.DataFrame:
    return pd.read_parquet(SAMPLE)


def observed(sample: pd.DataFrame, moment) -> dict:
    """Everything the fit needs at one minute, sliced here rather than inside the engine.

    **Strict minute, not as-of.** Served as-of, the same minute offers 41 both-sided
    strikes instead of 9 - but their quotes are up to 153 minutes apart, and since the
    regression's slope *is* the discount, mixing quote ages would put stale time-drift
    straight into D.
    """
    snap = sample[sample.ts == pd.Timestamp(moment)]
    paired = snap.pivot_table(index="strike", columns="option_type", values="last").dropna()
    return {
        "strikes": paired.index.to_numpy(float),
        "calls": paired.CE.to_numpy(float),
        "puts": paired.PE.to_numpy(float),
        "quoted_strikes": np.sort(snap.strike.unique()),
        "T": float(snap.dte_days.iloc[0]) / TRADING_DAYS_PER_YEAR,
        "spot": float(snap.spot.iloc[0]),
    }


def test_the_anchor_fits_the_forward_and_discount_section_one_publishes(sample):
    """D = 0.993480 and F-hat = 25,219.12, from 9 paired strikes spanning 24,500-25,500.

    The numbers `docs/calculations.md` section 1 publishes and the notebook asserts. The
    tolerance on the discount is the notebook's 1e-6: the discount *is* the slope, and a
    loose tolerance there would hide a wrong fit.
    """
    fit = forward.fit_forward(**observed(sample, ANCHOR))

    assert fit.method == "parity_fit"
    assert fit.pairs == 9
    assert fit.discount == pytest.approx(0.993480, abs=1e-6)
    assert fit.forward == pytest.approx(25_219.12, abs=1e-2)


def test_the_basis_at_the_anchor_is_a_hundred_and_nineteen_points(sample):
    """b = F-hat - S = +118.87.

    The basis is why the at-the-money strike moves a full 50-point interval, from 25,100
    to 25,200, and is the entire reason section 1 exists.
    """
    at = observed(sample, ANCHOR)
    fit = forward.fit_forward(**at)

    assert fit.forward - at["spot"] == pytest.approx(118.87, abs=1e-2)


def test_only_strikes_quoting_both_a_call_and_a_put_enter_the_fit(sample):
    """Parity needs a pair. 49 strikes are quoted at the anchor and 9 quote both sides.

    The fit reports its own sample size, so a change to the pairing rule shows up as a
    changed number rather than as a silently different line.
    """
    at = observed(sample, ANCHOR)

    assert len(at["quoted_strikes"]) == 49
    assert len(at["strikes"]) == 9
    assert forward.fit_forward(**at).pairs == 9


def test_every_minute_of_the_session_yields_a_forward(sample):
    """376 minutes, 376 forwards. No minute is refused and none returns a NaN.

    #51 originally forbade any fallback, leaving 60 minutes unanalysable. That was
    reversed: a refused minute takes the chain, the volatilities and every Greek down
    with it. ADR-0001's ban on NaN still holds - the ladder is total, not lenient.
    """
    moments = sorted(sample.ts.unique())
    assert len(moments) == 376

    for moment in moments:
        fit = forward.fit_forward(**observed(sample, moment))
        assert np.isfinite(fit.forward), f"{moment} produced a non-finite forward"
        assert np.isfinite(fit.discount), f"{moment} produced a non-finite discount"
        assert fit.forward > 0, f"{moment} produced a non-positive forward"
        assert 0 < fit.discount <= 1, f"{moment} produced discount {fit.discount}"


def test_the_session_splits_three_hundred_and_sixteen_fifty_and_ten(sample):
    """The measured shape of the day: 316 minutes carry a real fit, 50 fall to a
    single-strike parity, and 10 have no usable pair at the money and take spot.

    The 60 that miss the fit are the same 60 section 1 counted as rejections - 25 whose
    slope gives a discount above 1, 19 whose implied rate reaches 30%, and 16 with fewer
    than five pairs. They are no longer rejected, only demoted.
    """
    counted: dict[str, int] = {}
    for moment in sorted(sample.ts.unique()):
        method = forward.fit_forward(**observed(sample, moment)).method
        counted[method] = counted.get(method, 0) + 1

    assert counted == {"parity_fit": 316, "single_strike_parity": 50, "spot": 10}


def test_the_derived_values_reproduce_the_source_columns(sample):
    """The grade. Both columns, every minute, to 1e-6.

    This is the only assertion in the tree that opens `forward` or `discount`. Everywhere
    else they are absent by construction: `chain.load_chain()` drops them, so an engine
    that tried to read one would raise rather than return a plausible wrong answer.
    """
    worst_forward = worst_discount = 0.0
    for moment in sorted(sample.ts.unique()):
        snap = sample[sample.ts == moment]
        fit = forward.fit_forward(**observed(sample, moment))
        worst_forward = max(worst_forward, abs(fit.forward - float(snap.forward.iloc[0])))
        worst_discount = max(worst_discount, abs(fit.discount - float(snap.discount.iloc[0])))

    assert worst_forward < 1e-6, f"worst forward error {worst_forward}"
    assert worst_discount < 1e-6, f"worst discount error {worst_discount}"


def test_the_gate_sends_each_of_its_three_failures_down_to_parity(sample):
    """The gate chooses a tier; it no longer accepts or rejects a minute.

    All three ways of failing it are exercised on a named real minute: too few pairs to
    trust a line, a slope implying a discount above 1 (being paid to wait two weeks), and
    a slope implying a rate at or above 30%.
    """
    for moment in (
        PARITY_VIA_TOO_FEW_PAIRS,
        PARITY_VIA_DISCOUNT_ABOVE_ONE,
        PARITY_VIA_RATE_TOO_HIGH,
    ):
        assert forward.fit_forward(**observed(sample, moment)).method == "single_strike_parity"

    thin = forward.fit_forward(**observed(sample, PARITY_VIA_TOO_FEW_PAIRS))
    steep = forward.fit_forward(**observed(sample, PARITY_VIA_RATE_TOO_HIGH))

    assert thin.pairs < forward.MIN_PAIRS
    assert steep.pairs >= forward.MIN_PAIRS, "this minute must fail on the rate, not the count"


def test_parity_is_abandoned_only_when_the_money_strike_is_unpaired(sample):
    """The third tier is not a distance threshold.

    Single-strike parity is used exactly when the strike nearest spot quotes both sides,
    and abandoned when it does not. A threshold on how far the nearest *paired* strike
    sits from spot also separates these groups cleanly on this data - 25.3 against 29.4 -
    but that constant would have been fitted to the very column the grade reads. This
    rule has no constant in it.
    """
    for moment in (SPOT_VIA_UNPAIRED_ATM, SPOT_VIA_NO_PAIRS_AT_ALL):
        at = observed(sample, moment)
        fit = forward.fit_forward(**at)
        assert fit.method == "spot"
        assert fit.forward == pytest.approx(at["spot"])

    assert forward.fit_forward(**observed(sample, SPOT_VIA_NO_PAIRS_AT_ALL)).pairs == 0
    assert forward.fit_forward(**observed(sample, SPOT_VIA_UNPAIRED_ATM)).pairs == 3


def test_the_fallback_rate_supplies_the_discount_and_never_the_forward(sample):
    """r = 6.5% discounts; it does not price. F = S/D is measurably the wrong rule.

    Carrying the assumed rate through to the forward as S/D misses the source by a median
    of 54.63 points across the 60 fallback minutes - more than a full 50-point strike
    interval, and the same failure ADR-0001 records for the spot-to-forward conversion.
    The forward still has to come out of traded prices.
    """
    at = observed(sample, PARITY_VIA_DISCOUNT_ABOVE_ONE)
    fit = forward.fit_forward(**at)

    assert fit.discount == pytest.approx(float(np.exp(-forward.FALLBACK_RATE * at["T"])), abs=1e-12)
    assert abs(fit.forward - at["spot"] / fit.discount) > 50.0, "S/D agreed; the warning is stale"


def test_the_fitting_module_reads_no_data():
    """The guarantee `test_oracle.py` holds `pricing.py` to: the maths takes numbers and
    returns numbers. Slicing a chain belongs one layer up (ADR-0001)."""
    source = inspect.getsource(forward)

    assert "parquet" not in source
    assert "pandas" not in source
    assert "read_" not in source

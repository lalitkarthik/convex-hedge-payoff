"""The seed: the join every derived figure starts from, graded against what it replaced.

Until #67 there was one seed and it was a committed file. Generalising the build to all
twenty-four dates meant rebuilding the join that produced it - including `dte_days`, which
the old seed inherited from `Data/greeks.parquet` and which therefore did not exist for
the three dates that file is missing or thin on.

That makes this the riskiest change in the ticket, because it is the one that could move a
number silently: every `T`, every volatility and every Greek is downstream of the clock.
So it is graded twice, and both are exact rather than approximate.

**Against the Oracle**, on every row of it - 517,672 - across every date. `dte_days` is a
model input, so this is the Oracle being used as an Oracle, in the one file that opens it
alongside `test_oracle.py`, `test_forward.py` and `test_implied_vol.py`.

**Against the committed sample**, column for column on the anchor. That file is the
regression oracle for the join itself: it was built by a different script, from a
different set of files, by a different route, and if the two agree bit for bit then the
route did not matter.
"""

import ast
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from payoff import seed

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "Data" / "sample" / "chain_2026-01-27.parquet"
GREEKS = ROOT / "Data" / "greeks.parquet"

ANCHOR = date(2026, 1, 27)
EXPIRY = date(2026, 2, 10)

FIXTURE_BUILDERS = {"build_sample.py"}
"""The one script that is *allowed* to read the Oracle, and the reason the exemption is a
set of one rather than a rule.

`scripts/build_sample.py` writes `Data/sample/chain_2026-01-27.parquet`, which is the
Oracle for `test_oracle.py`, `test_forward.py` and `test_implied_vol.py` - it carries the
solved volatility and the eight shipped Greeks precisely because it joined that file. It
is a fixture builder, run by hand, imported by nothing, and on no path that serves a byte.

Since #67 nothing else needs it: the build reads the raw bars directly, and the sample is
the thing the engine is graded against rather than the thing it is built from.
"""


def test_the_dataset_holds_twenty_four_trading_dates():
    """Every one of which #67 builds and serves.

    Read off the bars rather than off a calendar, and the range is exactly why: it spans
    a **Sunday that traded** - 1 February, a Budget session NSE runs live at a weekend -
    and a Thursday that did not. No rule about weekdays produces this list.
    """
    dates = seed.trading_dates()

    assert len(dates) == 24
    assert dates[0] == date(2026, 1, 7)
    assert dates[-1] == EXPIRY
    assert date(2026, 2, 1) in dates, "the Sunday session is data, not a glitch"
    assert date(2026, 1, 15) not in dates, "and the missing Thursday has no bars"


def test_the_clock_counts_sessions_the_data_does_not_have_and_skips_one_it_does():
    """The two corrections that make `dte_days` reconstructable, and why each is needed.

    They pull in opposite directions and both are a whole session wide, which is 1/252 of
    a year on every `T` on the wrong side of them.
    """
    counted = seed.session_calendar()

    assert date(2026, 1, 15) in counted, "no bars, but the vendor's clock consumed it"
    assert date(2026, 2, 1) not in counted, "bars, but no time passed on it"

    # 30 Jan closes at 7.0 and 2 Feb opens at 7.0, which leaves the Sunday no room to
    # consume anything. It is served, and it sits flat.
    assert seed.sessions_to_expiry(date(2026, 1, 30), EXPIRY) == 8.0
    assert seed.sessions_to_expiry(date(2026, 2, 1), EXPIRY) == 7.0
    assert seed.sessions_to_expiry(date(2026, 2, 2), EXPIRY) == 7.0

    assert seed.sessions_to_expiry(ANCHOR, EXPIRY) == 11.0, "the anchor opens at 11"
    assert seed.sessions_to_expiry(EXPIRY, EXPIRY) == 1.0, "Expiry day opens at 1"


def test_the_reconstructed_clock_is_the_oracles_own_column_bit_for_bit():
    """The claim that lets the Oracle stop being an input at all.

    `dte_days` was the last column the engine read from `Data/greeks.parquet`, by way of
    the committed sample's inner join. `docs/data-quality.md` section 3 describes it
    completely enough to rebuild - sessions remaining, minus elapsed minutes over 375 -
    so the engine rebuilds it and this is the check that the description was complete.

    **Equality, not a tolerance.** `np.allclose` would pass on a formula that is a
    hundred ulps out, and a hundred ulps of `T` is a difference no assertion downstream
    would ever attribute back to here. The arithmetic had to be written as
    `N - i * (1/375)` rather than `N - i/375` to make this pass: the two disagree in the
    last bit on 3 of the anchor's 376 minutes.
    """
    oracle = pd.read_parquet(GREEKS, columns=["timestamp_utc", "dte_days"])
    oracle["ts"] = oracle.timestamp_utc.dt.floor("min")
    oracle["day"] = (oracle.ts + seed.IST_OFFSET).dt.date

    assert len(oracle) == 517_672

    mine = np.concatenate([
        seed.dte_days(day, rows.ts, EXPIRY) for day, rows in oracle.groupby("day", sort=True)
    ])
    theirs = np.concatenate([
        rows.dte_days.to_numpy(float) for _, rows in oracle.groupby("day", sort=True)
    ])
    assert np.array_equal(mine, theirs)


def test_the_anchors_seed_is_the_committed_one_column_for_column():
    """The regression oracle for the join, and the reason #67 could change it at all.

    `Data/sample/chain_2026-01-27.parquet` was built by `scripts/build_sample.py` out of
    three files, one of which this module no longer opens. If a seed built the new way
    from two files reproduces it bit for bit, then every figure the anchor serves is
    arithmetically identical to what it served before the ticket - which is the one
    acceptance criterion no HTTP assertion can establish on its own, since a rounding
    difference would pass every tolerance in `test_api_chain.py` and still be a change.
    """
    committed = pd.read_parquet(SAMPLE).sort_values(
        ["ts", "strike", "option_type"]
    ).reset_index(drop=True)
    mine = seed.seed(ANCHOR)

    assert len(mine) == len(committed) == 23_581
    for ours, theirs in (
        ("ts", "ts"), ("strike", "strike"), ("option_type", "option_type"),
        ("last", "last"), ("volume", "Volume"), ("open_interest", "OpenInterest"),
        ("spot", "spot"), ("dte_days", "dte_days"),
    ):
        assert np.array_equal(mine[ours].to_numpy(), committed[theirs].to_numpy()), ours


def test_the_engine_never_opens_the_oracle():
    """CONTEXT.md:138, made structural rather than enforced.

    Before #67 the guard was `derive.load_chain()` dropping the graded columns on the way
    in - which works, and which only works for as long as somebody remembers the list.
    Now the file is simply never opened outside `tests/`, so there is no column to drop
    and nothing to remember. That is a stronger property and a more fragile one: it is
    one convenient import away from being false, and nothing else in the suite would
    notice, because a Greek read from the Oracle looks exactly like a Greek that is right.

    Asserted over **live strings only**, parsed rather than grepped: several modules
    discuss the Oracle at length in their docstrings and should go on doing so. What must
    not exist is a string the interpreter could hand to a reader, which is every string
    constant that is not somebody's documentation.

    Walking the directories rather than naming the modules, so a file added tomorrow is
    covered without anyone remembering to add it here.
    """
    reachable = []
    for source in sorted((ROOT / "src").rglob("*.py")) + sorted((ROOT / "scripts").glob("*.py")):
        if source.name in FIXTURE_BUILDERS:
            continue
        tree = ast.parse(source.read_text(encoding="utf-8"))
        documentation = {
            id(node.value) for node in ast.walk(tree)
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
        }
        reachable += [
            source.name for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and "greeks" in node.value
            and id(node) not in documentation
        ]

    assert reachable == [], f"the Oracle is named in live code in {sorted(set(reachable))}"


@pytest.mark.parametrize(
    "day, quoted, minutes, strikes",
    [
        (date(2026, 1, 7), 244, 150, 12),
        (ANCHOR, 23_581, 376, 94),
        (EXPIRY, 45_330, 376, 98),
    ],
)
def test_each_day_is_as_thin_or_as_thick_as_it_actually_was(day, quoted, minutes, strikes):
    """The shape of the dataset, at both ends and at the anchor.

    Worth pinning because the sparse dates are the ones a build is most likely to get
    quietly wrong - 7 January quotes 12 strikes across 150 minutes, so a session-window
    filter that was one bar out, or a clock counted from the first bar rather than from
    the open, would change it visibly here and nowhere else.
    """
    frame = seed.seed(day)

    assert len(frame) == quoted
    assert frame.ts.nunique() == minutes
    assert frame.strike.nunique() == strikes
    assert frame.spot.notna().all(), "every quoted minute carries an index price"

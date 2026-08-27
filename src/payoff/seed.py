"""The seed: one trading day, joined out of the raw files, for any date in the dataset.

Until #67 there was exactly one seed - `Data/sample/chain_2026-01-27.parquet`, written by
`scripts/build_sample.py` - and the other twenty-three dates had none. Generalising the
build therefore meant generalising the **join**, not looping over a function that already
worked. This module is that join.

    Data/options.parquet   568,736 bars, IST, stamped at the bar close (`:59`)
    Data/index.parquet     NIFTY 50 spot, IST, same stamping, plus padding bars
      -> seed(date)        one day: ts (UTC), strike, option_type, last, volume,
                           open_interest, spot, dte_days

**`Data/greeks.parquet` is not opened here, and is not opened anywhere in `src/` or
`scripts/`.** The old seed was an inner join against it, which is where `dte_days` came
from and which is why three dates were partly or wholly missing from it - the Greeks
vendor skipped the 1 Feb Budget session entirely and stopped early on Expiry day
(`docs/data-quality.md` section 2). Section 3 turns out to describe that column
completely enough to rebuild it, so this module does, and the Oracle becomes a fixture
that feeds nothing at all rather than one that feeds a single input column.

The reconstruction is checked, not assumed: `dte_days` computed here is **bit-identical**
to the vendor's on all 517,672 rows it publishes, across every date, and the whole seed
is bit-identical to the committed sample on the anchor date. `tests/test_seed.py` asserts
both.
"""

from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parents[2] / "Data"
OPTIONS_FILE = DATA / "options.parquet"
INDEX_FILE = DATA / "index.parquet"

IST_OFFSET = pd.Timedelta(hours=5, minutes=30)
"""India observes no daylight saving, so the offset is +5:30 with zero exceptions across
the whole range (`docs/data-quality.md` section 2). Canonical timezone here is UTC."""

INDEX_TICKER = "NIFTY 50.NSE_IDX"
"""`index.parquet` carries two series; the other is NIFTY50 DIV POINT."""

SESSION_OPEN = timedelta(hours=9, minutes=15)
SESSION_CLOSE = timedelta(hours=15, minutes=30)
"""The NSE equity-derivatives session, in IST. `index.parquet` carries 815 flat
zero-volume padding bars outside it, at times as late as 21:40, and starts from 09:07."""

MINUTES_PER_SESSION = 375
"""One session of the trading-day clock, in minutes. `dte_days` steps by exactly 1/375 of
a session per bar and by **zero** overnight, so `T` measures market time and theta does
not accrue over a weekend (`docs/data-quality.md` section 3).

375 rather than 376 even though most sessions carry 376 bars: the session runs 09:15 to
15:30 *inclusive*, which is 376 stamps spanning 375 intervals."""

MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
"""Spelled out rather than left to `strptime('%b')`, which is locale-dependent - a machine
set to fr_FR would fail to parse `10FEB26`. `chain.MONTHS` is the same list going the
other way."""

SESSIONS_WITHOUT_BARS = (date(2026, 1, 15),)
"""Trading days the vendor's clock counted and this dataset has no bars for.

15 Jan 2026, a Thursday, is absent from all three files, yet `dte_days` decreases by a
full day across the gap (`docs/data-quality.md` section 2). Reconstructing the calendar
from the dates present would therefore be one session short for every date before it, and
every `T`, volatility and Greek on those eight dates would be wrong by 1/252 of a year."""

BARS_WITHOUT_SESSIONS = (date(2026, 2, 1),)
"""Dates this dataset has bars for and the vendor's clock did not count.

1 Feb 2026 is a **Sunday** - a full special session, almost certainly Budget day, which
NSE runs live even at a weekend. The Greeks vendor skipped it, and the arithmetic says it
consumed no time either way: 30 Jan closes at 7.0000 and 2 Feb opens at 7.0000, leaving
no room for a session in between. So the day is served, and it sits flat at 7.0
throughout. Theta does not accrue on it, which is what the clock says.
"""


def _expiry_of(ticker: str) -> date:
    """`NIFTY10FEB2625850PE.NFO` -> 2026-02-10.

    The expiry is only ever spelled on the instrument name; it is not a column. It
    becomes a partition key, so it has to come out as a sortable date rather than as the
    label a trader reads - `chain.expiry_label()` formats it back.
    """
    label = str(ticker).removeprefix("NIFTY")[:7]
    return date(2000 + int(label[5:7]), MONTHS.index(label[2:5]) + 1, int(label[:2]))


@lru_cache(maxsize=1)
def _options() -> pd.DataFrame:
    """Every option bar in the dataset, in UTC, with its expiry parsed off the Ticker.

    Read once for the build's lifetime. 568,736 rows is 8 MB on disk and re-reading it
    per date would be twenty-four passes over the same file.
    """
    frame = pd.read_parquet(OPTIONS_FILE)
    frame["ts"] = frame.DateTime.dt.floor("min") - IST_OFFSET
    frame["day"] = (frame.ts + IST_OFFSET).dt.date
    expiries = {ticker: _expiry_of(ticker) for ticker in frame.Ticker.unique()}
    frame["expiry"] = frame.Ticker.map(expiries)
    return frame


@lru_cache(maxsize=1)
def _spot() -> pd.DataFrame:
    """The NIFTY level, one bar per minute of the session, in UTC.

    Filtered twice: to the index series rather than the dividend-point series, and to the
    session window, because the padding bars are not trades and one of them landing on a
    join key would put a flat price against a live minute.
    """
    frame = pd.read_parquet(INDEX_FILE)
    frame = frame[frame.Ticker == INDEX_TICKER]
    stamped = frame.DateTime.dt.floor("min")
    ist = stamped - stamped.dt.normalize()
    within = (ist >= SESSION_OPEN) & (ist <= SESSION_CLOSE)
    return pd.DataFrame(
        {"ts": stamped[within] - IST_OFFSET, "spot": frame.Close[within].to_numpy(float)}
    )


@lru_cache(maxsize=1)
def trading_dates() -> tuple[date, ...]:
    """Every date this dataset holds option bars for, in order. Twenty-four of them.

    Read off the data rather than off a calendar: the range spans a Sunday that traded
    and a Thursday that did not, so no rule about weekdays reproduces this list.
    """
    return tuple(sorted(set(_options().day)))


@lru_cache(maxsize=1)
def session_calendar() -> tuple[date, ...]:
    """The sessions the trading-day clock counts, which is **not** the dates with bars.

    Two documented corrections, one in each direction, and both are load-bearing rather
    than tidy-minded: without the first, `dte_days` before 15 Jan is a whole session out;
    without the second, it is a whole session out from 1 Feb onwards.
    """
    return tuple(sorted(
        (set(trading_dates()) | set(SESSIONS_WITHOUT_BARS)) - set(BARS_WITHOUT_SESSIONS)
    ))


def sessions_to_expiry(day: date, expiry: date) -> float:
    """`dte_days` at the moment a session opens: how many sessions remain, counting this.

    So the anchor opens at 11.0 and closes at 10.0, and Expiry day opens at 1.0 and
    reaches 0.0 at its final bar. A date the clock does not count - 1 Feb - takes the
    next counted session's opening value and holds it, because that is the only value
    consistent with the sessions either side of it.
    """
    counted = session_calendar()
    if day in counted:
        return float(sum(1 for session in counted if day <= session <= expiry))
    return float(sum(1 for session in counted if day < session <= expiry))


def dte_days(day: date, stamps, expiry: date) -> np.ndarray:
    """The trading-day clock at each stamp: sessions remaining, minus elapsed minutes.

    Elapsed is measured from **09:15 IST on the calendar day**, not from the first bar
    that happened to print. The early dates are thin and open late - 7 Jan quotes 150
    minutes out of 376 - and counting from the first bar would shift the whole day.

    The arithmetic is written as `N - i * (1/375)` and not as `N - i/375`. The two differ
    in the last bit on 3 of the anchor's 376 minutes, and only the first reproduces the
    vendor's column exactly on all 517,672 rows it publishes. A one-ulp difference is
    invisible until it is the thing standing between a stored figure and the figure this
    day used to serve.
    """
    stamps = pd.to_datetime(pd.Series(np.asarray(stamps)))
    opened = datetime.combine(day, datetime.min.time()) + SESSION_OPEN - IST_OFFSET
    elapsed = (stamps - opened).dt.total_seconds().to_numpy() / 60.0
    return sessions_to_expiry(day, expiry) - elapsed * (1.0 / MINUTES_PER_SESSION)


def expiries_on(day: date) -> tuple[date, ...]:
    """Which Expiries traded on a date. One, throughout this dataset - but not by design.

    The tree is keyed by expiry under date, and the manifest records the pairing, so the
    day a second series appears it is a new prefix rather than a migration. Reading the
    set off the data rather than assuming it is what makes that true.
    """
    bars = _options()
    return tuple(sorted(set(bars.expiry[bars.day == day])))


def seed(day: date, expiry: date | None = None) -> pd.DataFrame:
    """One trading day's quoted bars, joined and ready to derive from.

    The three things `docs/data-quality.md` warns about are all here: both sources are
    floored to the minute and shifted out of IST before anything lines up, the index is
    filtered to one ticker and to the session, and `dte_days` is reconstructed rather
    than read. Joining on the raw timestamps returns zero rows, silently.

    Returns the **quoted** rows - one per strike, per side, per minute that traded. The
    carry-forward that fills the gaps is the build's job and happens after the
    volatilities are solved, because a quote is inverted in the minute it printed in.
    """
    if expiry is None:
        expiry = expiries_on(day)[0]

    bars = _options()
    rows = bars[(bars.day == day) & (bars.expiry == expiry)]
    frame = pd.DataFrame(
        {
            "ts": rows.ts.to_numpy(),
            "strike": rows.strike.to_numpy(float),
            "option_type": rows.option_type.to_numpy(),
            "last": rows.Close.to_numpy(float),
            "volume": rows.Volume.to_numpy(),
            "open_interest": rows.OpenInterest.to_numpy(),
        }
    ).merge(_spot(), on="ts", how="left")

    if frame.spot.isna().any():
        raise ValueError(f"{day}: {int(frame.spot.isna().sum())} bars carry no index price")

    frame["dte_days"] = dte_days(day, frame.ts, expiry)
    return frame.sort_values(["ts", "strike", "option_type"]).reset_index(drop=True)

"""Build the committed sample slice used by the golden-file tests.

Reads the three full parquet files and writes a single joined chain for one
trading day to Data/sample/. Small enough for CI to read in under a second.

The join is the whole point of this script. See docs/data-quality.md for why
it is not a one-liner:

  * options.parquet and index.parquet are stamped in IST; greeks.parquet is UTC.
  * options and index are stamped at the bar CLOSE (:59 seconds); greeks at :00.

So both have to be floored to the minute and shifted by 5h30m before anything
lines up. Joining on the raw timestamps returns zero rows, silently.

Usage:  python scripts/build_sample.py
"""

from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parents[1] / "Data"
OUT = DATA / "sample"
SAMPLE_DATE = "2026-01-27"
IST_OFFSET = pd.Timedelta(hours=5, minutes=30)

# NSE equity-derivatives session. Bars outside this are padding, not trades.
SESSION_OPEN = pd.Timestamp(SAMPLE_DATE + " 09:15").time()
SESSION_CLOSE = pd.Timestamp(SAMPLE_DATE + " 15:30").time()


def to_utc_minute(series: pd.Series, *, is_ist: bool) -> pd.Series:
    """Floor to the minute and normalise to UTC, the canonical join key."""
    out = series.dt.floor("min")
    return out - IST_OFFSET if is_ist else out


def main() -> None:
    options = pd.read_parquet(DATA / "options.parquet")
    greeks = pd.read_parquet(DATA / "greeks.parquet")
    index = pd.read_parquet(DATA / "index.parquet")

    options["ts"] = to_utc_minute(options.DateTime, is_ist=True)
    greeks["ts"] = to_utc_minute(greeks.timestamp_utc, is_ist=False)
    index["ts"] = to_utc_minute(index.DateTime, is_ist=True)

    day = pd.Timestamp(SAMPLE_DATE).date()
    in_day = lambda df: (df.ts + IST_OFFSET).dt.date == day  # noqa: E731

    options = options[in_day(options)]
    greeks = greeks[in_day(greeks)]
    spot = index[(index.Ticker == "NIFTY 50.NSE_IDX") & in_day(index)]

    # index.parquet carries flat zero-volume padding bars outside the session.
    ist = spot.ts + IST_OFFSET
    spot = spot[(ist.dt.time >= SESSION_OPEN) & (ist.dt.time <= SESSION_CLOSE)]
    spot = spot[["ts", "Close"]].rename(columns={"Close": "spot"})

    chain = (
        options[
            ["ts", "strike", "option_type", "Open", "High", "Low", "Close",
             "Volume", "OpenInterest", "Ticker"]
        ]
        .merge(
            greeks.drop(columns=["timestamp_utc", "underlying"]),
            on=["ts", "strike", "option_type"],
            how="inner",
        )
        .merge(spot, on="ts", how="left")
        .sort_values(["ts", "strike", "option_type"])
        .reset_index(drop=True)
    )

    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / f"chain_{SAMPLE_DATE}.parquet"
    chain.to_parquet(target, index=False, compression="zstd")

    size_mb = target.stat().st_size / 1e6
    print(f"wrote {target}  rows={len(chain):,}  {size_mb:.2f} MB")
    print(f"  minutes={chain.ts.nunique()}  strikes={chain.strike.nunique()}")
    print(f"  spot {chain.spot.min():.2f} -> {chain.spot.max():.2f}")
    print(f"  dte_days {chain.dte_days.min():.4f} -> {chain.dte_days.max():.4f}")
    assert chain.spot.notna().all(), "every minute must carry a spot"
    assert not chain.duplicated(["ts", "strike", "option_type"]).any()
    print("  assertions passed")


if __name__ == "__main__":
    main()

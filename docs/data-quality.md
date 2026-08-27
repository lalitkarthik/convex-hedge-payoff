# Data quality report

Produced while resolving [#6](https://github.com/lalitkarthik/convex-hedge-payoff/issues/6).
Covers the three files in `Data/`. Read this before writing any code that touches them.

## 1. The three files, and how they relate

| File | Rows | Timezone | Stamped at | Covers |
|---|---|---|---|---|
| `index.parquet` | 467,676 | **IST** | bar close (`:59`) | NIFTY 50 spot + NIFTY50 DIV POINT, 1-min, Dec 2023 – Apr 2026 |
| `options.parquet` | 568,736 | **IST** | bar close (`:59`) | NIFTY options 1-min OHLCV, 7 Jan – 10 Feb 2026, expiry `10FEB26` only |
| `greeks.parquet` | 517,672 | **UTC** | bar open (`:00`) | Solved IV, Greeks, forward, discount for the same options |

`greeks.parquet` is derived from `options.parquet`: after joining, **`options.Close == greeks.last` for
100.00% of matched rows**. The `last` column is the 1-minute bar close, not a separate tick feed.

## 2. The join

Two independent offsets have to be undone, and getting either wrong returns zero rows *silently* —
pandas will not warn you.

```python
IST_OFFSET = pd.Timedelta(hours=5, minutes=30)

options["ts"] = options.DateTime.dt.floor("min") - IST_OFFSET   # IST -> UTC, drop the :59
greeks["ts"]  = greeks.timestamp_utc.dt.floor("min")            # already UTC
index["ts"]   = index.DateTime.dt.floor("min") - IST_OFFSET
```

Join key: **`(ts, strike, option_type)`**. Canonical timezone: **UTC**.

Results:

| | rows |
|---|---|
| matched (`both`) | **517,672** — every single row of `greeks.parquet` |
| in `greeks` but not `options` | **0** |
| in `options` but not `greeks` | 51,064 |

The IST↔UTC offset is `+5:30` with **zero exceptions** across the whole range. India observes no
daylight saving, so this is safe to hardcode.

### The 51,064 unmatched option rows

Not random. They fall on exactly three dates:

| Date | Unmatched rows | Why |
|---|---|---|
| **2026-02-01** | 38,983 | **A Sunday.** A full special session with option trading and *no Greeks at all*. Almost certainly the Union Budget session — NSE runs live trading on Budget day even when it falls at a weekend. The Greeks vendor skipped it. |
| 2026-02-10 | 11,399 | Expiry day. Greeks stop before the session ends. |
| 2026-02-09 | 532 | Scattered minutes near expiry. |
| 2026-01-07 / others | ~150 | Isolated minutes, mostly early in the window when few strikes traded. |

**Consequence**: any code that iterates over trading days must not assume Mon–Fri, and must not assume
a Greeks row exists for every option row. Test against 2026-02-01 specifically.

### Missing trading day

**2026-01-15 (a Thursday) is absent from all three files**, yet `dte_days` decreases by a full day across
the gap — so the vendor's calendar counted it as a trading day while our data has no bars for it. If you
reconstruct a session calendar from the data, you will be one day short.

## 3. `dte_days` is a trading-time clock — this is the important one

`dte_days` does **not** measure calendar time, and it does not even measure whole trading days. It
measures **elapsed session minutes**.

Measured across all 23 sessions:

- Each session consumes **exactly 1.0000** unit, from open to close.
- The per-minute step is **1/375 = 0.00266667**.
- **The overnight gap is exactly 0.0000.** Close at 10.0000 on 27 Jan, open at 10.0000 on 28 Jan.
- Weekends and holidays likewise consume **zero**. 23 Jan closes at 11.0000; 27 Jan opens at 11.0000,
  with a weekend and Republic Day in between.

So on 27 Jan 2026 the value runs smoothly `11.000000` at 09:15 down to `10.000000` at 15:30.

**What this means in practice:**

- Time only passes while the market is open. **Theta accrues during the session and not overnight.**
- Combined with the finding in [#2](https://github.com/lalitkarthik/convex-hedge-payoff/issues/2) that
  `T = dte_days / 252`, one unit of `dte_days` is one 375-minute session, and 252 of them make a year.
  The convention is internally consistent.
- The target-date slider in the Sensibull UI moves in this clock, not in calendar days. Advancing
  "one day" is `-1.0`; advancing three hours mid-session is `-0.48`.

Minor wrinkle: sessions before 20 Jan carry 375 bars and close at `x.0027` rather than `x.0000`; from
20 Jan onward they carry 376 bars and close exactly. A one-bar inconsistency in the vendor's session
definition. Harmless, but do not assert exact integers at the close.

## 4. `index.parquet` needs filtering

- Contains **two** tickers. Filter to `Ticker == "NIFTY 50.NSE_IDX"`; the other is `NIFTY50 DIV POINT`.
- Carries **815 padding bars outside the session** — flat OHLC, `Volume == 0`, at times such as
  `16:00:59` and as late as `21:40:59`. These are not trades. Filter to `09:15`–`15:30` IST.
- Within the options window it has 414 bars per day against the session's 375, because it also starts
  before the open (from `09:07`).

## 5. Inputs versus oracle outputs

This distinction is what stops the engine cheating its own test. Columns split into three groups:

**Model inputs** — the engine is allowed to read these:

`strike` · `option_type` · `dte_days` · spot (from `index.parquet`)

`dte_days` is the odd one out: it is a model input that lives in the **oracle** file, so until
[#67](https://github.com/lalitkarthik/convex-hedge-payoff/issues/67) reading it was the one thread
still running from `greeks.parquet` into the engine — and it snapped on the three dates that file is
missing or thin on. §3 below turns out to describe the column completely enough to rebuild, so
`payoff/seed.py` rebuilds it from the session calendar and the minute of the day. The reconstruction
is **bit-identical** to the vendor's on all 517,672 rows it publishes; `tests/test_seed.py` asserts
that with `np.array_equal`, not a tolerance.

The upshot is that **nothing under `src/` or `scripts/` opens `greeks.parquet` at all.** The guard
used to be `derive.load_chain()` dropping the graded columns on the way in; it is now that the file
is never read outside `tests/`, which is a stronger claim and a more fragile one — so it is asserted
directly, over the parsed source of every module in both directories.

**Oracle outputs** — the engine computes these itself and is graded against them; it must never read them:

`forward` · `discount` · `iv` · `delta` · `gamma` · `theta` · `vega` · `rho` · `vanna` · `volga` · `charm`

`forward` and `discount` moved into this group with [#51](https://github.com/lalitkarthik/convex-hedge-payoff/issues/51),
which taught the engine to recover them from put-call parity (`docs/calculations.md` §1). Read
the distinction carefully, because it is easy to overstate: a forward and a discount factor are
still exactly what the pricing core wants as **arguments**, per ADR-0001. What changed is where
they may come from. Sourcing them from this file is now the thing that is banned. They are opened
in `tests/test_forward.py` and nowhere else.

**Market observables** — real prices, used to solve IV and to check repricing:

`last` (= `options.Close`) · `Open` / `High` / `Low` / `Volume` / `OpenInterest`

`iv` used to sit awkwardly between the groups, listed as a model input on the grounds that it is what
the Greeks are tested against. [#52](https://github.com/lalitkarthik/convex-hedge-payoff/issues/52)
settled it: **`iv` is not an input.** It is a solved quantity, the engine solves it from `last`
(`docs/calculations.md` §4). It is opened in `tests/test_implied_vol.py` and nowhere else in the
tree.

The same nuance applies as to `forward` and `discount`, and it is easy to overstate the ban. A
volatility is still exactly what `black76_greeks` wants as an **argument**, and a *test* may still
feed this column into it — that is what `tests/test_oracle.py` does to grade the Greeks, and it is
the Oracle being used as an Oracle. What is banned is the **engine** sourcing it from the file.

Never assert `model_price == last` across the whole file. It holds for **100.0%** of OTM rows and only
**6.2%** of ITM rows, because ITM prints are stale. That is a property of the market, not a bug.

## 6. The committed sample

`Data/sample/chain_2026-01-27.parquet` — 23,581 rows, 2.2 MB, built by `scripts/build_sample.py`.

Chosen because 27 Jan 2026 is:

- **gap-free** — 376 minutes, options and Greeks agree row for row;
- **liquid** — 94 of the 98 strikes present;
- **the widest clean day** — 505 points of intraday spot range, so payoff curves have something to bite on;
- **10.5 days from expiry** — clear of the near-expiry zone where the parity regression becomes
  ill-conditioned and Greeks coverage thins.

Verified: the Black-76 formulas from #2 reproduce this file's `delta` to `2.2e-16`, `gamma` to `2.2e-19`
and `vega` to `1.1e-14`.

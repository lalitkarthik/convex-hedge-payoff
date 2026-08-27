# Sample slice

`chain_2026-01-27.parquet` — one full trading day of NIFTY options, joined across all three source
files. 23,581 rows, 2.2 MB, 376 minutes, 94 strikes.

This is the fixture the golden-file tests run against. It is small enough for CI to read in well under
a second, and it is committed so that anyone who clones the repo can run the full test suite without
the 42 MB source files.

Rebuild with:

```bash
python scripts/build_sample.py
```

## Columns

| Group | Columns |
|---|---|
| Key | `ts` (UTC, minute), `strike`, `option_type` |
| Market | `Open`, `High`, `Low`, `Close`, `Volume`, `OpenInterest`, `last`, `Ticker`, `spot` |
| Model inputs | `dte_days` |
| Oracle outputs | `forward`, `discount`, `iv`, `delta`, `gamma`, `theta`, `vega`, `rho`, `vanna`, `volga`, `charm` |

`forward`, `discount` and `iv` are graded against, never read. The engine recovers the first two from
put-call parity (#51) and solves the third from the out-of-the-money `last` (#52).

Since #67 this file is **only** a fixture. It used to be the seed the runtime tree was built from, and
the guard against reading an Oracle column was `derive.load_chain()` dropping them on the way in. The
build now joins `options.parquet` and `index.parquet` itself, for all twenty-four dates, so nothing
under `src/` or `scripts/` opens this file or `greeks.parquet` at all — `tests/test_seed.py` asserts
that, and asserts that a seed built the new way reproduces this one column for column.

`ts` is **UTC**. Add 5h30m for IST. See [`docs/data-quality.md`](../../docs/data-quality.md) for why
that matters and for the full list of traps in the source data.

## Why this day

27 January 2026 is gap-free (options and Greeks agree row for row), liquid (94 of 98 strikes), has the
widest intraday range of any clean day (505 points), and sits 10.5 trading days from expiry — clear of
the near-expiry zone where the data thins out and numerics get unstable.

## What must not be asserted against it

`model_price == last` fails on in-the-money rows by design. `iv` is solved from the out-of-the-money
leg and shared with its ITM twin, whose last print is stale — the shared value is a **copy**, exact to
the last bit, not two solves that agree. Grade against the Greeks columns instead.

One case the "out-of-the-money leg" phrasing does not cover: on **392** strike-minutes only the
in-the-money leg printed, and its `iv` is solved from that print. See `docs/calculations.md` §4.

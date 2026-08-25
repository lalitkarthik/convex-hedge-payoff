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
| Model inputs | `dte_days`, `iv` |
| Oracle outputs | `forward`, `discount`, `delta`, `gamma`, `theta`, `vega`, `rho`, `vanna`, `volga`, `charm` |

`forward` and `discount` are graded against, never read: the engine recovers both from put-call
parity (#51). `chain.load_chain()` drops them, so the runtime frame does not carry them at all.

`ts` is **UTC**. Add 5h30m for IST. See [`docs/data-quality.md`](../../docs/data-quality.md) for why
that matters and for the full list of traps in the source data.

## Why this day

27 January 2026 is gap-free (options and Greeks agree row for row), liquid (94 of 98 strikes), has the
widest intraday range of any clean day (505 points), and sits 10.5 trading days from expiry — clear of
the near-expiry zone where the data thins out and numerics get unstable.

## What must not be asserted against it

`model_price == last` fails on in-the-money rows by design. `iv` is solved from the out-of-the-money
leg and shared with its ITM twin, whose last print is stale. Grade against the Greeks columns instead.

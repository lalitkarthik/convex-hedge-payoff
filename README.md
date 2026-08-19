# convex-hedge-payoff

A Sensibull-style **payoff calculator** for NIFTY index options: pick option contracts, see what the
position makes or loses at expiry, with max profit, max loss and breakevens.

### 👉 New here? Read [`docs/onboarding.md`](./docs/onboarding.md).

Fifteen minutes to a passing test suite, forty-five to your first ticket.

---

**The deliverable is understanding, not the app.** This is a learning project between two
developers. We reimplement Black-76 rather than importing it, and `Data/greeks.parquet` is a **test
oracle** rather than an input — we compute the Greeks ourselves and CI fails if they drift from it
by more than `1e-6`. If the numbers match, the maths is understood.

| | |
|---|---|
| The living plan | [Map #1](https://github.com/lalitkarthik/convex-hedge-payoff/issues/1) |
| The v1 spec | [#23](https://github.com/lalitkarthik/convex-hedge-payoff/issues/23) |
| Implementation tickets | #24 – #32, labelled `ready-for-agent` |
| Vocabulary | [`CONTEXT.md`](./CONTEXT.md) |
| How we work | [`CONTRIBUTING.md`](./CONTRIBUTING.md) |
| Decisions | [`docs/adr/`](./docs/adr/) |
| Data traps | [`docs/data-quality.md`](./docs/data-quality.md) |

State lives in the issues, not in files. If the map and a file disagree, the map wins.

## Quick start

```
python -m venv .venv && source .venv/bin/activate    # .venv\Scripts\activate on Windows
pip install -r requirements.txt -r requirements-dev.txt
pytest          # expect: 6 passed
ruff check .    # expect: no output
```

Those two commands are exactly what CI runs. Then open
`notebooks/01_payoff_structures.ipynb` and run all cells — everything we are building already works
there, and the project is largely the act of moving it into a package without changing a number.

The clone is ~46 MB because the market data is committed on purpose, so tests and CI need no
external setup.

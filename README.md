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
pytest          # expect: 101 passed
ruff check .    # expect: no output
```

Those two commands are exactly what CI runs. Then open
`notebooks/01_payoff_structures.ipynb` and run all cells — everything we are building already works
there, and the project is largely the act of moving it into a package without changing a number.

The clone is ~46 MB because the market data is committed on purpose, so tests and CI need no
external setup.

## Running the website

Two processes. The engine serves JSON; the frontend renders it and proxies to it, so the browser
only ever talks to its own origin and no cross-origin policy exists to misconfigure (#25).

```bash
# terminal 1 - the engine
PYTHONPATH=src .venv/bin/python -m uvicorn payoff.api:app --port 8000

# terminal 2 - the frontend  (needs bun; there is no npm on the dev machine)
cd web && bun install
BACKEND_ORIGIN=http://127.0.0.1:8000 bun run dev
```

Then open **http://localhost:3000**. Two pages:

| | |
|---|---|
| `/` | the Chain. Click **B** or **S** on a strike, or pick a Preset. |
| `/analyse?moment=…&legs=…` | the chart, the metrics, the Greeks and the payoff table. |

The Strategy lives in the URL, so the link you copy *is* the position — paste it into a fresh tab
and the identical chart comes back.

`BACKEND_ORIGIN` defaults to `http://127.0.0.1:8000`, so the second variable is only needed when
the engine is somewhere else.

### Checking the frontend

```bash
cd web
bun test lib/        # units: the URL codec and the API client
bunx tsc --noEmit
bun run build

# the integration check - needs both servers up, and a browser
E2E=1 bun run e2e
```

`bun test lib/` needs nothing running. The e2e drives a real browser against a real engine and is
the only check that catches a broken rewrite or a renamed field on the seam; CI runs it on every
pull request that touches `web/` or `src/payoff/`.

### After changing `models.py`

The frontend's wire types mirror the schema, and two tests hold them to it:

```bash
.venv/bin/python scripts/dump_openapi.py     # rewrites web/openapi.json
```

Then update `web/lib/types.ts` to match. `tests/test_openapi_contract.py` fails if the committed
schema drifts from the app; `tests/test_wire_types.py` fails if the TypeScript drifts from the
schema.

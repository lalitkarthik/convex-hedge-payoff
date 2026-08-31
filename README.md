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
pytest          # expect: 179 passed
ruff check .    # expect: no output
```

Those two commands are exactly what CI runs. Then open
`notebooks/01_payoff_structures.ipynb` and run all cells — everything we are building already works
there, and the project is largely the act of moving it into a package without changing a number.

The clone is ~46 MB because the market data is committed on purpose, so tests and CI need no
external setup. The *derived* tree the engine serves from is not committed - it is a build
product - so `tests/conftest.py` derives it once per session on the way in, and that sentence
stays true.

## Running the website

### With Docker

One command, on a machine that has only Docker installed:

```bash
docker compose up
```

Then open **http://localhost:3000**. The engine derives the runtime tree on first start —
about 55 seconds, once, into a named volume; later starts take about four. Source is
bind-mounted and both services reload on edit, so no rebuild is needed while working.

`docker compose down` keeps the volume. `docker compose down -v` discards it and forces the
tree to be derived again. Commands and the traps behind them are in
[`docs/docker.md`](./docs/docker.md).

### Without Docker

Two processes, and one build before them. The engine serves JSON; the frontend renders it and
proxies to it, so the browser only ever talks to its own origin and no cross-origin policy
exists to misconfigure (#25).

The engine **reads** the numbers it serves; it no longer solves them (#66). Deriving a day
costs about 1.4 s and the day cannot change, so it happens once, here, and lands in
`Data/runtime/` - which is gitignored, being derived rather than authored. A fresh clone has to
run this. The engine raises and names this command if the tree is missing, rather than quietly
re-deriving and putting the cost back into the first request.

Since #67 the build derives **every trading date in the dataset** - twenty-four of them,
1,062,024 rows, about fifty seconds - and `/chain` takes a `date`. The test suite builds three
of the twenty-four rather than all of them; `tests/conftest.py` says which and why.

It writes a **per-minute summary** beside the Chain (#69): Spot, the Forward, the Discount
Factor and the at-the-money volatility belong to the minute rather than to a strike, and in the
Chain they repeat across all ~196 of that minute's rows. Stored once they are 8,735 rows for
the whole dataset against 1,062,024, and `/summary` is what the header and the time control
read - so dragging the time control no longer opens the large file. The figures are the ones
`/chain` publishes for the same minute, because the summary is reduced from the Chain frame on
its way to disk rather than derived a second time.

```bash
# once - derive every day the engine serves
PYTHONPATH=src python scripts/build_runtime.py

# or just the ones you need, while iterating
PYTHONPATH=src python scripts/build_runtime.py --dates=2026-01-27,2026-02-10
```

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

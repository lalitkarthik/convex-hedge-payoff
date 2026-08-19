# Onboarding — start here

You have repo access and no context. This gets you to a passing test suite in about fifteen
minutes, and to your first ticket in about forty-five.

Read it top to bottom once. Everything else in the repo is linked from here.

---

## 1. Get it running (15 min)

```
git clone https://github.com/lalitkarthik/convex-hedge-payoff.git
```
The clone is **~46 MB** — the market data is committed, deliberately, so that CI and the tests can
read it without any external setup. Don't be alarmed by the size.

```
cd convex-hedge-payoff
python -m venv .venv
```
`.venv/` is gitignored.

```
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux
```

```
pip install -r requirements.txt -r requirements-dev.txt
```
`requirements.txt` is the notebook stack; `requirements-dev.txt` is pytest, ruff and nbconvert.
CI runs on **Python 3.12**; anything 3.10+ should be fine locally.

```
pytest
```
**Expect `6 passed` in under a second.** If it fails, stop and say so — nothing downstream is worth
debugging until this is green.

```
ruff check .
```
Expect no output. These two commands are exactly what CI runs, so if both pass locally your pull
request will pass too.

```
jupyter lab notebooks/01_payoff_structures.ipynb
```
Run all cells. It takes about thirty seconds and it is the single most useful thing you can do on
day one — it prices real options, compares them against pre-solved values, draws payoff charts, and
prints `check passed` three times. **Everything we are building is in that notebook already.** The
project is largely the act of moving it into a package without changing a number.

---

## 2. What this is, and the one rule

We are building a Sensibull-style **payoff calculator** for NIFTY index options: pick some option
contracts, see what the position makes or loses at expiry, with max profit, max loss and breakevens.

**The rule that changes everything: the deliverable is understanding, not the app.**

This is a learning project. Shipping a working calculator quickly would *fail* the objective. The
goal is that either of us can read any line of the code — including code an AI wrote — and say
whether the maths is right. That is why:

- We **reimplement** Black-76 instead of `pip install`ing a library that does it.
- `Data/greeks.parquet` is a **test oracle**, never an input. It contains pre-solved Greeks. We
  compute our own and assert they match, to 1e-6, in CI. If they match, we understood the maths.
- Decisions get argued out and written down before code is written. Twelve issues are closed with
  their reasoning; you can read why anything is the way it is.

So: if an agent hands you something that works and you can't explain why, that's a problem to raise,
not a win to merge.

---

## 3. Where the state actually lives

**GitHub issues, not files.** The repo holds decisions; the issues hold the plan.

| What | Where |
|---|---|
| The living plan and every settled decision | **[Map #1](https://github.com/lalitkarthik/convex-hedge-payoff/issues/1)** |
| The v1 spec | [#23](https://github.com/lalitkarthik/convex-hedge-payoff/issues/23) |
| The nine implementation tickets | #24 – #32 |
| Vocabulary | [`CONTEXT.md`](../CONTEXT.md) |
| Workflow rules | [`CONTRIBUTING.md`](../CONTRIBUTING.md) |
| Architectural decisions | [`docs/adr/`](./adr/) |
| Data traps | [`docs/data-quality.md`](./data-quality.md) |

If the map and a file disagree, **the map wins** and the file needs fixing.

---

## 4. Reading order (30 min)

1. **[`CONTEXT.md`](../CONTEXT.md)** — 22 terms. Do not skip this. Several words in options trading
   are genuinely ambiguous and this file is what stops the two halves of the codebase meaning
   different things by "payoff". In particular: **Payoff** is premium-blind terminal value, **P&L**
   is that minus what you paid, and both chart lines are P&L. Also: a **Strategy** is just an
   ordered list of **Legs** — "iron condor" is a label, not a type.
2. **[Map #1](https://github.com/lalitkarthik/convex-hedge-payoff/issues/1)**, the "Decisions so
   far" section. Every closed ticket, one line each, with the evidence.
3. **[`docs/adr/0001`](./adr/0001-core-takes-forward-not-spot.md)** — why the pricing core takes a
   *forward* and not a *spot*. This one surprises people, which is why it is written down.
4. **[Spec #23](https://github.com/lalitkarthik/convex-hedge-payoff/issues/23)** — what v1 is, 50
   user stories, and what is deliberately out of scope.
5. **[`CONTRIBUTING.md`](../CONTRIBUTING.md)** — branch names, commit format, who reviews what.

If you only read two: `CONTEXT.md` and the map.

---

## 5. Pick a ticket

Nine tickets, #24 to #32, all labelled `ready-for-agent`. They carry **native GitHub blocking
links**, so GitHub itself tells you what is startable.

```
gh issue list --label ready-for-agent --state open
```

A ticket is yours when it has **no open blockers** and **no assignee**. To take it:

```
gh issue edit 24 --add-assignee @me
```
Assign yourself *before* you start, so we don't both build the same thing.

The order is not a suggestion — the blocking edges are real:

```
#24 engine→API ─┬─> #25 browser + deploy ─┬─> #27 Greeks Table
   (start here) │                          ├─> #28 chain picker ─┬─> #30 presets
                │                          └─> #29 payoff table  ├─> #31 errors
                └─> #26 oracle in CI ──────> #27                 └─> #32 shareable links
```

**#24 is the only one with no blockers**, so whoever starts first takes it. Once it lands, #25 and
#26 open together and we can work in parallel.

### How the work splits

By **layer**, not by feature, so we edit disjoint files:

| Owner | Owns |
|---|---|
| dev A | the pricing core, the golden test, the FastAPI app |
| dev B | strategy aggregation, presets, chain loading, the Next.js app |
| **both** | the shared types module — **the seam** |

You review the half you don't own. The shared types module is the one file where we agree **before**
the pull request opens, not after.

---

## 6. The workflow

Short-lived branches off `main`, pull request, the other person reviews and merges. Nobody merges
their own. `main` is protected and **enforces this on admins too** — a direct push is rejected,
verified rather than assumed.

Full rules in [`CONTRIBUTING.md`](../CONTRIBUTING.md). The short version:

```
git checkout -b feat/payoff-curve
# ... work ...
git add <specific files>          # never git add -A
git commit -m "feat(strategy): P&L at expiry for an arbitrary leg list"
git push -u origin feat/payoff-curve
gh pr create
```

Branch prefixes: `feat/`, `fix/`, `docs/`, `chore/`, `research/`, `data/`, `hotfix/`.

**`hotfix/` means production is broken right now.** It does not mean "a feature I want soon". Adding
a feature to a working deploy is `feat/`. Keeping that distinction is what makes the deliberate
hotfix exercise in [#12](https://github.com/lalitkarthik/convex-hedge-payoff/issues/12) teach
anything.

Commit bodies should say what you **verified**, with a number someone can check. A reviewer who can
re-run your claim is worth more than one who has to trust your paragraph.

---

## 7. The traps

Each of these cost real time to find. All are already documented; none should be rediscovered.

**The timezone join.** `options.parquet` is stamped IST at the bar *close* (`:59`);
`greeks.parquet` is UTC at the bar *open* (`:00`). Joining them naively returns wrong or zero rows
**silently** — no error, no warning. Floor to the minute *and* shift IST by 5h30m. Full write-up in
[`docs/data-quality.md`](./data-quality.md).

**Implied volatility is one value per strike.** It is solved from the out-of-the-money option and
shared with its in-the-money twin — verified on 100% of both-sided strikes. Consequences: the golden
test must assert against the Greeks columns and **never** against the last-price column, and the UI
shows one shared IV column rather than one per side.

**Theta is not the textbook formula.** In this data it is a one-trading-day repricing. Against the
oracle, the repricing definition matches to `4.5e-12`; the analytic formula is off by `4.1e-01`.
Write the analytic one and your tests will fail for a reason that looks like a bug and isn't.

**Time is a trading-day clock.** One session is exactly 1.0 day. Nothing decays overnight or at
weekends. Years are trading days ÷ 252, not ÷ 365.

**The chain is sparse.** Only strikes that actually traded in a given minute have a bar. At a
typical moment just **9 of 49** strikes quote both a call and a put. Serving the last known quote
at or before the requested time gives **41**. Ticket #28 covers this.

**Never resolve a notebook conflict in the GitHub web editor.** A `.ipynb` is JSON with base64 image
blobs and execution counts. Resolve locally, usually by taking one side wholesale
(`git checkout <branch> -- notebooks/...`) and re-running it.

**Don't fix the same thing on two branches.** This already happened: the lot size was corrected on
three branches in one afternoon, and reconciling them cost more than the one-line change was worth.
If a fix is in flight, wait for the merge.

**Never return `NaN`.** Banned in the core by
[ADR-0001](./adr/0001-core-takes-forward-not-spot.md) and banned on the wire by the API contract.
A `NaN` renders as an invisible gap in a chart and survives code review. Raise instead.

---

## 8. Do this on day one

**Turn on required reviews.** Right now `main` requires a pull request and passing checks, but the
required approval count is **0** — because with one developer, requiring an approval would have
deadlocked the repo. You are the second developer, so it should be 1:

```
gh api --method PATCH repos/lalitkarthik/convex-hedge-payoff/branches/main/protection/required_pull_request_reviews \
  -F required_approving_review_count=1
```

Until that runs, "the other dev reviews and merges" is convention rather than enforcement.

---

## 9. Working with Claude on this repo

`CLAUDE.md` loads automatically and points at the glossary, the workflow and the ADRs, so a fresh
session starts with the vocabulary.

The pipeline we've been using, in order: **wayfinder** (map out what needs deciding) → **grilling**
(argue a decision to a conclusion) → **to-spec** → **to-tickets** → **implement**. The first four
are done for v1. You are at *implement*.

`docs/agents/` configures those skills for this repo — GitHub as the tracker, the five standard
triage labels, single-context domain docs. It is already set up; you shouldn't need to touch it.

Two habits worth copying:

- **Make it prove things.** Ask for the number, not the adjective. Most of the decisions in the map
  are backed by a measurement precisely because the first answer was a guess and the measurement
  disagreed with it.
- **Explain it back.** If you can't say why the generated code is right, it isn't done — that is the
  whole point of the project, and the golden test is the automated version of the same instinct.

---

## Questions worth asking early

Better raised on day one than in week three:

- Anything in `CONTEXT.md` that doesn't match how you'd use the word. The glossary is meant to be
  argued with; a term that only one of us understands is worse than no term.
- Anything in the map's decisions that looks wrong. They are recorded with their evidence
  specifically so they can be challenged rather than inherited.
- Ticket granularity. If #24 turns out to be too big for one sitting, say so — splitting it is
  cheaper than a stalled branch.

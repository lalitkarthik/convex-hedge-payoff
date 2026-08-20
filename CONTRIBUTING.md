# Contributing

Two developers, one `main`, GitHub Flow. `main` is always deployable.

Read [`CONTEXT.md`](./CONTEXT.md) before writing anything — several words in this
domain are ambiguous, and the glossary is what stops the two halves of the codebase
meaning different things by "payoff".

## The loop

1. Branch off `main`.
2. Commit small, with a Conventional Commit subject.
3. Open a pull request. CI must be green.
4. The **other** developer reviews and merges.
5. Delete the branch.

Nobody merges their own pull request, and nobody pushes to `main`. `main` is
protected, so both of those are enforced rather than requested.

## Branch names

```
feat/<what>        a new capability          feat/payoff-curve
fix/<what>         a bug in something merged fix/lot-size-65
docs/<what>        documentation or an ADR   docs/context-glossary
chore/<what>       tooling, CI, config       chore/ci-and-branch-protection
research/<what>    a notebook or a spike     research/payoff-notebook
data/<what>        anything under Data/      data/reconciled-slice
hotfix/<what>      production is broken now  hotfix/chart-blank-on-load
```

`hotfix/` means the deployed application is broken. It does **not** mean "a feature
I would like soon". Adding probability of profit to a working deploy is `feat/`.
Keeping that distinction is the difference between the hotfix exercise teaching
something and being theatre.

## Commit messages

Conventional Commits: `type(scope): subject`, imperative mood, no trailing full stop.

```
feat(pricing): vectorised Black-76 price and greeks
fix(research): set NIFTY lot size to 65 and re-execute the notebook
docs(adr): 0001 - the core takes a forward, not a spot
```

The body is where the value is. Say what changed, and say what you verified — a
number a reviewer can check beats a paragraph they have to trust:

> Verified: all three assertions still pass. Every currency figure scales by 65/75
> and nothing else moves — Long Straddle max loss goes from -50,306 to -43,599,
> which is 670.75 x 65, and the breakevens stay at 24529.25 / 25870.75 because
> breakevens do not depend on lot size.

## Who reviews what

The split is **by layer**, agreed in [#11](https://github.com/lalitkarthik/convex-hedge-payoff/issues/11):

| Owner | Files |
|---|---|
| dev A | `src/payoff/pricing.py`, the golden-file test |
| dev B | `src/payoff/strategy.py`, `pop.py`, `presets.py`, `chain.py` |
| **both** | `src/payoff/models.py` — the seam |

You review the half you do not own. `models.py` changes need both of you to agree
before the pull request is opened, not after — it is the one file where a merge
conflict is a symptom rather than an accident.

## CI

| workflow | runs | on |
|---|---|---|
| `ci.yml` | `ruff check` and `pytest` | every pull request and push to `main` |
| `notebook.yml` | executes every notebook | only when `notebooks/`, `Data/` or `requirements.txt` change |

Notebooks are **executed**, not merely linted. The golden-file test has moved into
`tests/test_oracle.py` (#26), so the oracle assertions now run in the standard `test`
job rather than in the notebook. `notebooks/01_payoff_structures.ipynb` covers the
payoff structures instead, and still carries the straddle premium check and the
defined-risk cap arithmetic. A rotted notebook is a rotted proof. It is path-filtered
because it is the slow job and most pull requests cannot break it.

The ruff ruleset is deliberately narrow to begin with (`E`, `F`, `I`, `W`). Tighten
it once there is code to tighten against.

## Never do this

- **Fix the same thing on two branches.** The lot size was corrected three times in
  one afternoon — on `fix/lot-size-65`, on `docs/context-glossary` and on
  `research/payoff-notebook` — and reconciling them cost more than the one-line
  change was worth. If a fix is already in flight, wait for the merge.
- **Resolve a notebook conflict in the GitHub web editor.** A `.ipynb` is JSON with
  base64 image blobs and execution counts. Resolve it locally, usually by taking one
  side wholesale with `git checkout <branch> -- notebooks/…`, then re-execute.
- **Return `NaN`.** [ADR-0001](./docs/adr/0001-core-takes-forward-not-spot.md) bans it
  in the core and the API contract bans it on the wire. A `NaN` renders as a silent
  gap in a payoff chart and survives review.

## Learning exercises

Two things are run deliberately, and the write-up **is** the deliverable — including
whatever went wrong:

- **The hotfix.** Introduce a visible bug, merge it, watch the deployed app break,
  then branch `hotfix/…`, repair it, and watch it heal.
- **The long-lived branch.** Keep a feature branch open for a week while `main` moves
  underneath it, then merge it and feel the conflict. This is the pain that killed
  Gitflow, and reading about it is not the same as resolving it.

Both belong to [#12](https://github.com/lalitkarthik/convex-hedge-payoff/issues/12)
and both need a live deployment first.

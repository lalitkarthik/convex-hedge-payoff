# convex-hedge-payoff

A Sensibull-style payoff engine for NIFTY index options, built by two developers as a learning
project. The stated goal is that both devs can read any line of generated code and say whether the
maths is right — so the engine reimplements Black-76 rather than importing it, and
`Data/greeks.parquet` is a **test oracle**, never an input.

Start here:

- [`docs/onboarding.md`](./docs/onboarding.md) — if this session is new to the project, read this
  first. Setup, the reading order, how tickets are picked, and the traps that have already cost
  time once.
- [`CONTEXT.md`](./CONTEXT.md) — the domain glossary. Read it before writing anything; several terms
  in this domain are ambiguous and this file is what stops the two halves of the codebase meaning
  different things by "payoff".
- [`CONTRIBUTING.md`](./CONTRIBUTING.md) — branch naming, commit format, who reviews what, and the
  mistakes already made once.
- [`docs/adr/`](./docs/adr/) — architectural decisions.
- [`docs/data-quality.md`](./docs/data-quality.md) — the IST/UTC join trap and the trading-day clock.
- The live plan is the **wayfinder map**, issue
  [#1](https://github.com/lalitkarthik/convex-hedge-payoff/issues/1), not this file.

## Agent skills

### Issue tracker

Issues live as GitHub issues on `lalitkarthik/convex-hedge-payoff`, driven through the `gh` CLI.
See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical roles, each label string equal to its name: `needs-triage`, `needs-info`,
`ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` and one `docs/adr/` at the repo root. See `docs/agents/domain.md`.

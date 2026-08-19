# The pricing core takes a forward and a discount factor, never a spot and a rate

The payoff chart's x-axis is **spot**, so the obvious core signature is
`price(spot, strike, T, rate, vol, is_call)`. We rejected it. The core takes
`(forward, strike, T, vol, discount, is_call)`, and converting a hypothetical spot into
a forward is the strategy layer's job — the core never sees a spot.

## Why

Issue #2 established that `greeks.parquet` is reproduced by **Black-76 on the forward**,
matching all 517,672 rows to machine epsilon. Black-76 consumes `F` and `D` directly. A
core that accepted spot and rate would have to reconstruct them internally, and the
reconstruction is the unstable part:

- The implied continuous rate `r = -ln(D)/T` runs from **0.9% to 28.4%** across the
  dataset and diverges as `T -> 0` (#2, #13).
- The basis `F - S` is not a constant and not always positive: measured over all 8,356
  timestamps it runs **-26.45 to +233.04**, with a median of +20.39 (#13).
- On **2,397 of 8,356 minutes (28.7%)** the parity regression cannot fit a forward at all
  and falls back to `F = S`. Those minutes quote a median of 7 strikes against 87 on
  healthy minutes (#13).

Hiding any of that inside a pricing function would make the core's output depend on a
conversion rule nobody chose deliberately, and would make it disagree with the oracle for
reasons invisible at the call site.

## Consequences

- **The core is trivially testable against the oracle.** `greeks.parquet` ships `forward`
  and `discount` as columns, so a golden test feeds the core exactly what it wants with no
  conversion step in between. If the test fails, the maths is wrong — not the plumbing.
- **The spot-to-forward rule (#13) lives above the seam**, in `strategy.py`, where it is one
  named function that can be changed, argued about and tested in isolation.
- **The seam moves work to the strategy layer.** That layer owns the chain, the spot series
  and the conversion; the core owns only the formulas.
- Anyone reading `pricing.py` and expecting a spot argument will be surprised. That is the
  reason this file exists.

## Considered and rejected

- **`price(spot, ...)` with an internal conversion.** Rejected: it buries a contested
  decision (#13 lists three defensible conversion rules that disagree) inside a function
  whose job is arithmetic.
- **`price(spot, ...)` with the rate passed in.** Rejected: it still needs a carry rule to
  get from spot to forward, and it invites callers to pass the unstable implied `r`.

# Calculations

Every formula the payoff engine uses, and where each one is verified. One section per
calculation. If a number appears in the notebook or the API, its derivation is here.

## Notation

| Symbol | Meaning |
|---|---|
| $S$ | spot — the index level now |
| $S_T$ | terminal spot — the index level at expiry, the payoff x-axis |
| $F$ | forward — the index level the options are priced off |
| $K$ | strike |
| $D$ | discount factor to expiry, $D = e^{-rT}$ |
| $r$ | continuously compounded rate implied by $D$ |
| $T$ | time to expiry in years, $T = \texttt{dte\_days} / 252$ |
| $C, P$ | call and put price at strike $K$ |
| $q_i$ | quantity of leg $i$, $d_i = \pm 1$ for bought / sold |
| $L$ | lot size, 65 for NIFTY |

`dte_days` is a **trading-day clock**: one session consumes exactly 1.0, weekends and
holidays none. Established in [#2](https://github.com/lalitkarthik/convex-hedge-payoff/issues/2).

---

## 1. Forward and discount, from put-call parity

**We do not read $F$ and $D$ from the data. We derive them from the option prices.**

For European options on the same underlying, strike and expiry, put-call parity is an
identity — no model, no volatility, no distributional assumption:

$$C(K) - P(K) = D\,(F - K)$$

Read it as a function of $K$ and it is already a straight line:

$$\underbrace{C(K) - P(K)}_{y} \;=\; \underbrace{DF}_{a} \;+\; \underbrace{(-D)}_{b}\,K$$

So a single ordinary least squares fit of $y$ on $K$ recovers **both** unknowns from the
slope and the intercept:

$$\boxed{\;\hat D = -b \qquad \hat F = \frac{a}{\hat D} = -\frac{a}{b}\;}$$

### Which strikes enter the fit

Only strikes quoting **both** a call and a put at that minute — parity needs a pair, and
one side alone says nothing. At the 12:00 snapshot that is 9 of the 94 strikes touched
during the day.

A moneyness filter of $0.85 \le K/F \le 1.15$ is specified upstream. On this dataset it
is **inert**: across the whole session $K/F$ on paired strikes spans only 0.9218 to
1.1024, so the filter drops 0 of 4,585 pairs. It also cannot be applied as written —
$F$ is the unknown being solved for, so the filter is circular unless a proxy for $F$ is
used first. Retained as documentation of intent, not as a working constraint.

### The accept gate

OLS returns a number whether or not the input deserves one. A fit is used only if:

$$n \ge 5 \qquad \text{and} \qquad 0 < \hat r < 30\%, \quad \hat r = -\frac{\ln \hat D}{T}$$

Rejected minutes produce visibly broken fits — $\hat D$ from 0.9415 to 1.0195, implied
rates from $-46.7\%$ to $+146.6\%$. A discount factor above 1 is a negative interest rate
over a two-week horizon; it renders as a plausible-looking chart that is wrong, which is
the failure mode [ADR-0001](./adr/0001-core-takes-forward-not-spot.md) exists to prevent.

**Minutes failing the gate are out of scope for v1 and are not displayed.** The upstream
data does fall back on them — $r = 6.5\%$ fixed, with $F$ from a single-strike parity at
the strike nearest spot, or $F = S$ when no pair is usable. We deliberately do not
implement that. Recorded here so it is not rediscovered from scratch.

### Verification

The fit is graded against the `forward` and `discount` columns of the source data, which
were produced independently.

| | ours | source | difference |
|---|---|---|---|
| $\hat D$ | 0.993480 | 0.993480 | $+0.000000$ |
| $\hat F$ | 25,219.12 | 25,219.12 | $+0.00$ |

$n = 9$, $R^2 = 0.99989$, $\hat r = 15.61\%$. Asserted in the notebook, so the `execute`
CI job fails if the formula drifts.

Across the full session the same fit reproduces the source **exactly on 316 of 376
minutes**. The other 60 are precisely the minutes the gate rejects, where the upstream
fallback takes over. That is the evidence this is the same method, not a method that
happens to agree at one moment.

### Where $F$ and $D$ are used

- $F$ selects the at-the-money strike — the strike nearest the **forward**, not the spot.
  At the snapshot they differ by 118.87 points, which is more than two strike intervals,
  and they select different strikes (25,200 against 25,100).
- $F$ and $S$ are both drawn on the payoff chart as reference lines. The position never
  depends on which one you look at.
- $D$ is not yet consumed downstream. It falls out of the same fit for free and will be
  needed the moment anything is priced before expiry.

---

## 2. Payoff at expiry

At expiry every option is worth its **intrinsic value** — all time value is gone:

$$C_T = \max(S_T - K,\ 0) \qquad P_T = \max(K - S_T,\ 0)$$

Profit and loss on one leg is what it ends up worth minus what it cost, signed by
direction and scaled by quantity and lot size:

$$\text{P\&L}_i(S_T) = d_i\,q_i\,\bigl(V_i(S_T) - p_i\bigr)\,L$$

where $V_i$ is the intrinsic value above and $p_i$ the entry price. A strategy is the sum
over its legs:

$$\text{P\&L}(S_T) = \sum_i \text{P\&L}_i(S_T)$$

Nothing here needs $F$, $D$, $T$ or volatility. The expiry payoff is arithmetic on
strikes and entry prices, which is why it is the only line v1 draws.

---

## 3. Max profit, max loss, breakevens

The expiry payoff is **piecewise linear** with a kink at every strike, so these come from
an exact method rather than a numerical search.

**Slopes in the tails.** Far above the highest strike every call is in the money and every
put worthless, so the payoff is a straight line of slope

$$m_{\text{right}} = \sum_{i \in \text{calls}} d_i q_i$$

Below the lowest strike, symmetrically,

$$m_{\text{left}} = -\sum_{i \in \text{puts}} d_i q_i$$

**Max profit and max loss.** Any interior extremum must sit at a kink, so evaluating at
every strike plus $S_T = 0$ gives every candidate. The tails then decide whether an
extremum is finite:

$$\text{max profit} = \begin{cases} \infty & m_{\text{right}} > 0 \\ \max(\text{candidates}) & \text{otherwise}\end{cases}
\qquad
\text{max loss} = \begin{cases} -\infty & m_{\text{right}} < 0 \\ \min(\text{candidates}) & \text{otherwise}\end{cases}$$

Only the upside is genuinely unbounded — $S_T$ cannot fall below zero, so the left tail
always terminates.

**Breakevens.** Sign changes are located on a fine grid, then solved exactly inside each
bracket by Brent's method. Roots of a piecewise-linear function, not an approximation.

**Defined-risk check.** A structure with $m_{\text{left}} = m_{\text{right}} = 0$ has both
tails flat, so both caps are finite and forced by arithmetic:

$$\text{max profit} = \text{net credit} \qquad \text{max loss} = \text{net credit} - (\text{wing width} \times L)$$

Asserted in the notebook for the iron fly and iron condor, which is how the metrics
function is checked against something that does not depend on it.

---

## 4. Greeks

**Not derived yet.** The engine has a Black-76 core in `src/payoff/pricing.py` graded
against the source greeks in CI, but nothing in the payoff view consumes it, and the
notebook no longer prices anything.

When position greeks return, the derivation belongs here. Two questions must be settled
first, and neither is:

- **Spot-to-forward conversion** — pricing at a hypothetical spot needs a rule mapping
  $S \to F$, and the data cannot referee it.
  [#13](https://github.com/lalitkarthik/convex-hedge-payoff/issues/13)
- **Volatility on a target date** — whether implied vol is held constant.
  [#8](https://github.com/lalitkarthik/convex-hedge-payoff/issues/8)

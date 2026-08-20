# Calculations

Every formula the payoff engine uses. One section per calculation. If a number appears in
the notebook or the API, its derivation is here.

## Notation

| Symbol | Meaning |
|---|---|
| $S$ | spot — the index level now |
| $S_T$ | terminal spot at expiry — the payoff x-axis in **spot** coordinates |
| $\hat F$ | the forward **now**, fitted in §1 — the level options are priced off |
| $F$ | the forward as a **payoff coordinate**, $F = S_T + b$ |
| $b$ | basis, $b = \hat F - S$ |
| $K$ | strike |
| $D$ | discount factor to expiry, $D = e^{-rT}$ |
| $r$ | continuously compounded rate implied by $D$ |
| $T$ | time to expiry in years, `dte_days` / 252 |
| $C, P$ | call and put price at strike $K$ |
| $d_i, q_i, p_i$ | direction ($\pm 1$), quantity and entry price of leg $i$ |
| $L$ | lot size, 65 for NIFTY |

`dte_days` is a trading-day clock: one session consumes exactly 1.0, weekends and holidays
none.

---

## 1. Forward and discount

**Derived from the option prices, not read from the data.**

Put-call parity is an identity for European options on the same underlying, strike and
expiry. No model, no volatility, no distributional assumption:

$$C(K) - P(K) = D \, (\hat F - K)$$

As a function of $K$ that is a straight line, $y = a + mK$, with

$$y = C(K) - P(K), \qquad a = D\hat F, \qquad m = -D$$

So one ordinary least squares fit recovers both unknowns:

$$D = -m \qquad \hat F = \frac{a}{D} = -\frac{a}{m}$$

Only strikes quoting **both** a call and a put can enter — parity needs a pair. At the
12:00 snapshot that is 9 of the 94 strikes touched during the day.

### Verification

Graded against the `forward` and `discount` columns, solved independently upstream:

| | ours | source | difference |
|---|---|---|---|
| $D$ | 0.993480 | 0.993480 | $+0.000000$ |
| $\hat F$ | 25,219.12 | 25,219.12 | $+0.00$ |

$n = 9$, $R^2 = 0.99989$, $r = 15.61\%$. Asserted in the notebook, so CI fails if the
formula drifts. Across the full session the same fit reproduces the source **exactly on
316 of 376 minutes**.

### The gate

OLS returns a number whether the input deserves one or not. A fit is used only if

$$n \ge 5 \qquad \text{and} \qquad 0 < r < 30\%, \qquad r = -\frac{\ln D}{T}$$

### Rejecting $F = S/D$

[#13](https://github.com/lalitkarthik/convex-hedge-payoff/issues/13) question 1 offers three
rules for mapping a hypothetical spot to a forward. **One of them is excluded on this data:**

```
F = S / D          ->  25,264.98     observed 25,219.12     miss +45.86
F = S + b          ->  25,219.12     exact by construction
F = S x (F-hat/S)  ->  25,219.12     exact by construction
```

$S/D$ reinstates the full financing cost and none of the offsetting dividend income, because
the fitted $D$ is a **pure discount**. The 45.86-point miss is a strike interval wide — larger
than the basis it is trying to reproduce.

The remaining two disagree by under 7 points across $\pm 6\%$ of spot. **Constant basis is
adopted for charting** (§2), because it makes the transform a rigid translation and so lets the
caps be asserted unchanged rather than merely observed to be close. This narrows #13 question 1
from three candidates to two; it does not answer it, and a charting convention is not a pricing
rule.

### Why 60 minutes fail it

Of the 376 minutes in the session:

| | minutes |
|---|---|
| accepted | 316 |
| discount above 1 — a negative rate | 25 |
| implied rate above 30% | 19 |
| fewer than 5 paired strikes | 16 |

**The forward is robust; the discount is fragile.** They come from different features of
the same line:

- $\hat F$ is where the line **crosses zero** — set $C - P = 0$ and parity gives $K = \hat F$
  directly. A zero-crossing inside the strike range is an interpolation, and noise barely
  moves it.
- $D$ is the **slope**. Measuring a slope means measuring the line's tilt across the
  strike range, and a small tilt error is a large $D$ error.

The data shows exactly that. On the 60 rejected minutes our forward is still within
**1.64 points (median)** of the source, worst case 13.58 — while the discount goes from a
tight 0.9874–0.9997 on accepted minutes to **0.9415–1.0195** on rejected ones.

The 09:15 minute is typical. Ten well-traded pairs, nothing obviously wrong:

```
strike      CE       PE      C-P
25000    459.70   231.85   227.85
25200    341.70   311.60    30.10
25500    203.30   466.90  -263.60
25700    139.60   609.30  -469.70

slope  = -1.002361   ->  D = 1.002361,  r = -5.40%
```

A discount factor above 1 means being *paid* to wait two weeks. The fit is not obviously
broken — the slope is off by under 1% — but that is enough, because $D$ *is* the slope.
The narrower the strike range, the worse it gets: rejected minutes span a median of 850
strike points, accepted ones 1,300.

**Rejected minutes are out of scope for v1 and are not displayed.** The upstream data does
fall back on them — a fixed $r = 6.5\%$, with $F$ from a single-strike parity at the strike
nearest spot, or $F = S$ when no pair is usable. We deliberately do not implement that.
Recorded so it is not rediscovered from scratch.

### A note on the moneyness filter

A filter of $0.85 \le K/\hat F \le 1.15$ is specified upstream. On this data it is **inert**:
across the session $K/\hat F$ on paired strikes spans only 0.9218 to 1.1024, so it drops 0 of
4,585 pairs. It is also circular as written — $\hat F$ is the unknown being solved for. Kept as
documentation of intent; the gate above does the work.

### Where $\hat F$ and $D$ are used

- $\hat F$ selects the at-the-money strike — nearest the **forward**, not the spot. At the
  snapshot they differ by 118.87 points and select different strikes, 25,200 against
  25,100.
- $\hat F$ and $S$ are both drawn on the payoff chart. The position never depends on which one
  you read.
- $D$ is not consumed downstream yet. It falls out of the same fit for free and is needed
  the moment anything is priced before expiry.
- $b = \hat F - S$ **is** consumed. It is the whole content of the forward-coordinate payoff
  view in §2, and the only quantity by which the two payoff charts differ.

---

## 2. Payoff at expiry

At expiry an option is worth its **intrinsic value** — all time value is gone:

$$C_T = \max(S_T - K, \; 0) \qquad P_T = \max(K - S_T, \; 0)$$

Profit and loss on one leg is what it ends up worth minus what it cost, signed by direction
and scaled by quantity and lot size. Writing $V_i$ for the intrinsic value above:

$$\text{PnL}_i(S_T) = d_i \, q_i \, (V_i(S_T) - p_i) \, L$$

A strategy is the sum over its legs:

$$\text{PnL}(S_T) = \sum_i \text{PnL}_i(S_T)$$

Nothing here needs $\hat F$, $D$, $T$ or volatility. The expiry payoff is arithmetic on strikes
and entry prices, which is why it is the only line v1 draws.

### The same payoff in forward coordinates

A leg settles against **spot**, so the formulas above are unavoidably functions of $S_T$. To read
the payoff against the forward instead, substitute $S_T = F - b$:

$$\max(S_T - K,\;0) = \max\bigl(F - (K + b),\;0\bigr)
\qquad
\max(K - S_T,\;0) = \max\bigl((K + b) - F,\;0\bigr)$$

So in forward coordinates **the effective strike is $K + b$**, and

$$\Pi_F(F) = \Pi(F - b)$$

The forward payoff is the spot payoff **translated right by $b$**. Nothing else happens to it.
That is why constant basis was chosen over the constant-ratio rule, which scales instead and
would stretch strike gaps unevenly.

It is exact **only at expiry**, where the realised basis is zero — it uses today's basis for a
payoff settled later. It is a way of reading the expiry line and must not be carried onto a
target-date curve without revisiting [#8](https://github.com/lalitkarthik/convex-hedge-payoff/issues/8).

---

## 3. Max profit, max loss, breakevens

The expiry payoff is **piecewise linear** with a kink at every strike, so these are exact,
not searched for.

**Tail slopes.** Above the highest strike every call is in the money and every put
worthless, so the payoff is a straight line of slope $m_R$. Below the lowest strike,
symmetrically, $m_L$:

$$m_R = \sum_{i \in \text{calls}} d_i q_i \qquad m_L = -\sum_{i \in \text{puts}} d_i q_i$$

**Caps.** Any interior extremum sits at a kink, so evaluating at every strike plus
$S_T = 0$ gives every candidate. The tails then decide whether a cap is finite: max profit
is unbounded when $m_R > 0$, max loss when $m_R < 0$, otherwise both are the extremes of
the candidates. Only the upside is genuinely unbounded — $S_T$ cannot fall below zero, so
the left tail always terminates.

**Breakevens.** Sign changes located on a fine grid, then solved exactly inside each
bracket by Brent's method.

**Defined-risk check.** When $m_L = m_R = 0$ both tails are flat, so both caps are finite
and forced by arithmetic:

$$\text{max profit} = \text{credit} \qquad \text{max loss} = \text{credit} - (\text{wing width} \times L)$$

Asserted in the notebook for the iron fly and iron condor — a check on the metrics function
that does not depend on it.

### In forward coordinates

$\Pi_F(F) = \Pi(F - b)$ is a translation, so:

1. **Max profit, max loss and net premium are identical** in both coordinate systems. A
   horizontal shift moves no $y$-value, and premiums are prices paid — they have no axis at all.
2. **Every breakeven shifts by exactly $+b$.**
3. **The left tail terminates at $F = b$, not $F = 0$**, because $S_T \ge 0$ maps to $F \ge b$.

The third is a trap. The candidate set becomes

$$\mathcal{K}_F = \{b\} \cup \{K_i + b\}$$

Reusing $0$ evaluates the payoff at $S_T = -b$, a negative index. Measured on the naked long put
at the 12:00 snapshot, ATM 25,200, $L = 65$:

```
correct   max profit at F = b = 118.87   ->  1,616,764.50
naive     max profit at F = 0            ->  1,624,490.77     wrong by +7,726.27
```

It does not raise, does not produce `NaN`, and is 0.48% high — it would survive review. The
mitigation is structural: **compute the metrics once in spot coordinates, where the floor is
unambiguously zero, then translate the $x$-quantities.** No second candidate set then exists to
get wrong.

---

## 4. Greeks

**Not derived yet.** A Black-76 core exists in `src/payoff/pricing.py` and is graded against
the source greeks in CI, but nothing in the payoff view consumes it.

Two questions block the derivation, and neither is settled:

- Spot-to-forward conversion — pricing at a hypothetical spot needs a rule mapping
  $S \to F$, and the data cannot referee it.
  [#13](https://github.com/lalitkarthik/convex-hedge-payoff/issues/13)
  The constant-basis convention adopted in §2 is a **charting** choice for the expiry line, and
  is not an answer to this — a settled chart axis is not a settled pricing rule.
- Volatility on a target date — whether implied vol is held constant.
  [#8](https://github.com/lalitkarthik/convex-hedge-payoff/issues/8)

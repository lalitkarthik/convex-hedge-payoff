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
| $\sigma$ | implied volatility, a decimal — never a percentage |
| $N(\cdot), n(\cdot)$ | standard normal CDF and density |
| $d_1, d_2$ | the Black-76 arguments, defined in §4 |
| $\Delta, \Gamma, \nu, \Theta$ | delta, gamma, vega and theta of a single contract |
| $g_i$ | any one Greek of leg $i$ |

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

## 4. Implied volatility

Everything above is arithmetic. This needs a **model**, and it has no closed form.

Black-76 maps a volatility to a price and is strictly increasing in $\sigma$ — more volatility is
always worth more — so the map is invertible, but only numerically:

$$\text{price} = \text{Black76}(\hat F, K, T, \sigma, D) \qquad \Longrightarrow \qquad \sigma = \;?$$

Implied volatility is the $\sigma$ that reproduces the quoted price. It is not a forecast. It is
the price restated in units that compare across strikes.

### Newton-Raphson

Drive the residual to zero:

$$f(\sigma) = \text{Black76}(\hat F, K, T, \sigma, D) - \text{market}$$

The derivative is a Greek we already have — **vega**:

$$f'(\sigma) = D\,\hat F\,\phi(d_1)\sqrt{T}, \qquad
d_1 = \frac{\ln(\hat F/K) + \tfrac{1}{2}\sigma^2 T}{\sigma\sqrt{T}}$$

$$\sigma_{n+1} = \sigma_n - \frac{f(\sigma_n)}{f'(\sigma_n)}$$

**The vega must be raw.** `black76_greeks` returns vega divided by 100, because the Oracle quotes
it per volatility *point*. Feeding that to Newton makes every step 100 times too small: the
solver still converges, just far too slowly, so it presents as sluggishness rather than as a bug.

### Which quote to invert

One volatility per strike, from the **out-of-the-money** leg: the call when $K \ge \hat F$, the
put when $K < \hat F$.

Forced, not chosen. The Oracle's `iv` is identical for the call and the put at every paired
strike — it solves the OTM leg and copies the answer to the in-the-money twin, whose last print
is stale. Inverting the ITM quote disagrees with the Oracle by construction. See
`Data/sample/README.md`.

### Convergence

Newton replaces the curve by its tangent and jumps to where the tangent crosses zero. Near the
root the error **squares** every step — the correct digits double. Traced on the 25,500 call,
seeded at 0.20:

```
step        sigma          error    price residual
   0   0.20000000       4.11e-02          8.07e+01
   1   0.15930075       3.84e-04          7.46e-01
   2   0.15891634       5.35e-08          1.04e-04
   3   0.15891629       5.00e-16          1.17e-12
```

Four correct digits, then eight, then full double precision. That is why a tolerance of $10^{-8}$
costs 4 iterations rather than 40.

**That behaviour is local.** It holds once the guess is near the root and says nothing about a
guess that is not. Price against $\sigma$ is S-shaped: as $\sigma \to 0$ the price flattens onto
intrinsic and vega decays super-exponentially, because $\phi(d_1)$ carries $e^{-d_1^2/2}$ while
$d_1$ itself grows like $1/\sigma$. On that flat shelf the tangent is horizontal and the step
$f/f'$ diverges.

### The seed decides whether it works at all

The textbook seed is Brenner-Subrahmanyam,
$\sigma_0 \approx \sqrt{2\pi/T}\;\text{price}/(D\hat F)$, derived at the money. Off the money it
is badly wrong, and the vega it lands on is not merely small:

```
23,500 PE   market 23.75   true iv 21.36%

              sigma        d1      phi(d1)        vega
BS seed      0.0116    29.715    7.41e-193    3.80e-189
flat 0.20    0.2000     1.745     8.70e-02     4.46e+02
true iv      0.2136     1.636     1.05e-01     5.36e+02
```

The seed is 18 times too low, and vega there is **191 orders of magnitude** below its value at
the answer. No step size recovers from that; the solver aborts on the $10^{-12}$ guard.

Measured across all 46 legs of the slice:

| seed | converged | median iterations |
|---|---|---|
| Brenner-Subrahmanyam | **22 / 46** | 5 |
| $\max(\text{BS},\,\sqrt{2\lvert \ln(\hat F/K)\rvert / T})$ | 46 / 46 | 6 |
| flat $\sigma_0 = 0.20$ | **46 / 46** | **4** |

A flat 20% wins on both counts. The chain quotes 15.7% to 21.4%, so a constant is never far from
any root, and the cleverer seeds buy nothing. **The naive seed beats the derived one here**, and
the reason is specific rather than general: one expiry, a narrow volatility range, and a known
market.

### Verification

Graded three ways at the 12:00 snapshot, 46 legs, all asserted in the notebook:

| check | result |
|---|---|
| against the Oracle `iv` | max difference $7.92 \times 10^{-12}$ |
| round-trip repricing | max difference $3.70 \times 10^{-9}$ |
| iteration ceiling | max 5, median 4 |

The iteration ceiling is a real check, not decoration — it is what catches the divided-by-100
vega, which produces correct answers slowly rather than wrong answers loudly.

### What the slice shows

Volatility against moneyness $K/\hat F$ at one minute — a two-dimensional cut, since one expiry
gives no second axis. Two distinct features, routinely conflated:

**Smile.** Both wings sit above the middle. The minimum is 15.74% at $K/\hat F = 1.033$; the far
put reaches 21.36% and the far call 21.11%. Away from the money in either direction the market
charges more than one flat volatility, because real tails are fatter than lognormal.

**Skew.** The wings are not level with each other:

| distance from $\hat F$ | put | call | put $-$ call |
|---|---|---|---|
| 3% | 18.20% | 15.82% | +2.38 |
| 5% | 19.61% | 16.60% | +3.01 |
| 7% | 21.36% | 17.87% | +3.49 |

The put side is dearer at every distance and the gap widens further out — downside protection
costs more than equivalent upside.

---

## 5. Greeks

Delta, gamma, vega and theta, per contract and per structure, from the same Black-76 the rest of
this file uses.

### What each one is

The definitions matter more than the formulas, because the parts that go wrong go wrong silently.
True of all four, so stated once:

| | |
|---|---|
| **model** | **Black-76** — lognormal *forward*, reimplemented in `src/payoff/pricing.py` and graded against the oracle in CI, never imported |
| **underlying variable** | the **forward** $\hat F$, fitted in §1 from put-call parity. **Never the spot.** No $S \to F$ conversion appears anywhere in this section, which is why #13 can stay open |
| **position size** | **one contract** — not one lot, not a structure's quantity, not signed by direction. Multiply by $L = 65$ for a lot; the aggregation below applies $d_i$ and $q_i$ |
| **valuation moment** | the observed one. At the 12:00 IST snapshot of 27 Jan 2026 that is $T = 0.041905$ years, 10.56 trading days from the 10 Feb expiry |
| **clock** | **trading days**, `dte_days / 252`. A weekend or a holiday consumes nothing (§0) |
| **volatility** | $\sigma$ per strike from §4's Newton solve on that strike's out-of-the-money quote; one $\sigma$ shared by the call and the put |
| **discounting** | $D$ from the same §1 fit. All four carry it |
| **held fixed** | everything not named as the perturbation — in particular $\sigma$ does not move when $\hat F$ does |

$d_1$ and $d_2$ are §4's, unchanged, with $N$ the standard normal CDF and $n$ its density:

$$d_1 = \frac{\ln(\hat F/K) + \tfrac{1}{2}\sigma^2 T}{\sigma\sqrt{T}}, \qquad d_2 = d_1 - \sigma\sqrt{T}$$

#### $\Delta$ — one point of forward

$$\Delta = \frac{\partial V}{\partial \hat F} = D\,N(d_1) \quad \text{(call)}, \qquad
  D\bigl(N(d_1) - 1\bigr) \quad \text{(put)}$$

Perturbs the forward by one index point, holding $\sigma$, $T$ and $D$. Units: rupees of contract
value per point of forward. Range $[0, D]$ for a call and $[-D, 0]$ for a put — *not* $[0, 1]$,
because the payoff is discounted; a $\Delta$ of exactly 1 would mean an undiscounted convention.
No time scale: it is a slope at this instant and this forward.

#### $\Gamma$ — how fast $\Delta$ itself moves

$$\Gamma = \frac{\partial^2 V}{\partial \hat F^2} = \frac{D \, n(d_1)}{\hat F \, \sigma \sqrt{T}}$$

The same perturbation, but the *second* derivative: the change in $\Delta$ per point, not the
change in value. Units: $\Delta$ per point, per contract — two orders of magnitude smaller than
the other three at this expiry, which is why the tables below carry seven decimals. Always
positive for a long option, call or put alike. No time scale, but it grows as $T \to 0$.

#### $\nu$ — one volatility **point**

$$\nu = \frac{\partial V}{\partial \sigma} \times \frac{1}{100}
      = \frac{D \, \hat F \, n(d_1) \sqrt{T}}{100}$$

Perturbs $\sigma$ by **one percentage point** — 16.43% to 17.43%, not 0.1643 to 1.1643. The
$/100$ is exactly that rescaling. Only that strike's $\sigma$ moves, so this is a per-strike
sensitivity rather than a parallel shift of the smile. Units: rupees per volatility point, per
contract. No time scale.

#### $\Theta$ — one trading session, by repricing

$$\Theta = V\!\left(T - \tfrac{1}{252},\; D_{\text{next}}\right) - V(T, D),
  \qquad D_{\text{next}} = e^{-r\left(T - \frac{1}{252}\right)}, \qquad r = -\frac{\ln D}{T}$$

Perturbs the clock by **exactly one trading session** — not one calendar day and not an
infinitesimal. The method is reprice-and-subtract: this one is a **difference, not a derivative**.
$\hat F$ and $\sigma$ are held; $T$ and $D$ move together. Units: rupees per session, per
contract, already scaled — do not divide by 252 again. Negative for a long option, positive for a
short one. Bounded by the premium, since a long option cannot lose more in a day than it is worth
— which the analytic derivative is not, and that is the whole of *Rejecting the analytic $\Theta$*
below.

$\Gamma$ and $\nu$ depend on the strike only through $d_1$, which a call and a put at one strike
share, so **they are identical for the two**. Only $\Delta$ knows which side it is on, and the two
differ by exactly $D$ — put-call parity differentiated, since
$\partial\bigl[D(\hat F - K)\bigr] / \partial \hat F = D$. An undiscounted convention reports 1
there; this one reports 0.9934799840 at the 12:00 snapshot, and the notebook asserts it.

The rate is reconstructed from $D$ only to roll the discount one session. Per **ADR-0001** it is
never an input and never leaves the function: the implied continuous rate runs from 0.9% to 28.4%
across the dataset and diverges as $T \to 0$.

### Where these sit against the benchmark's conventions

$\Delta$, $\Gamma$ and $\nu$ are partial derivatives of the Black-76 price with the **discount
factor left in** — the price is $D\bigl[\hat F N(d_1) - K N(d_2)\bigr]$, so every derivative of it
carries the $D$. `Data/greeks.parquet` drops it on two of them, which is a market convention
rather than an error:

| | here | `Data/greeks.parquet` | the gap |
|---|---|---|---|
| $\Delta$ | $D\,N(d_1)$ | $N(d_1)$ | a factor of $D$ |
| $\Gamma$ | $D\,n(d_1)/(\hat F \sigma\sqrt{T})$ | undiscounted | a factor of $D$ |
| $\nu$ | $D\,\hat F\,n(d_1)\sqrt{T}/100$ | the same | none |
| $\Theta$ | a one-session **repricing** | the same | none |

The first two are a **scaling and nothing more**. $\partial V/\partial \hat F$ really is
$D\,N(d_1)$: the premium is paid today and the payoff arrives at expiry, so a point of forward is
worth a discounted point now. Dropping the $D$ is what the benchmark ships, and the two numbers
are one multiplication apart.

$\Theta$ is the exception to the pattern, and it is deliberate. It is not $\partial V/\partial t$
but what the contract is worth after one session — the number a trader reads $\Theta$ as, what the
benchmark ships, and the form that survives the measurement below.

### Rejecting the analytic $\Theta$

The obvious form is the derivative, divided down to one session:

$$\Theta_{\text{analytic}} = \frac{1}{252}\left(-\frac{D \, \hat F \, n(d_1) \, \sigma}{2\sqrt{T}}
  \;+\; r\,V\right)$$

It is what every reference prints, and it is what the other three Greeks here already are — which
is exactly why it needs rejecting in writing rather than by omission. Measured against the
benchmark at the 12:00 snapshot, over all 55 gradeable legs:

```
                      analytic     source        miss

25,200 PE             -15.7064   -16.1119     +0.4055     at the money, 2.52%
25,200 CE             -15.6946   -16.1002     +0.4055
26,050 CE              -9.3031    -9.2985     -0.0047     far wing

one-session repricing                       4.1e-10
```

The miss is largest at the money, shrinks into the wings and keeps the same sign throughout. That
is what makes it dangerous rather than merely wrong: no outlier, no `NaN`, no exception — a Greeks
table built on it would understate the decay of every near-the-money position by a couple of
percent, all day.

Over the whole of `Data/greeks.parquet` it is worse than a couple of percent, and the shape of the
failure is the argument. The analytic form carries a $1/\sqrt{T}$ and **diverges into the final
session**; a repricing cannot, because a contract cannot lose more in a day than it is worth:

| `dte_days` | rows | worst abs | median abs | median rel |
|---|---|---|---|---|
| [0, 0.5) | 13,596 | 90.638 | 8.2846 | 1280.85% |
| [0.5, 1) | 20,213 | 21.681 | 5.2371 | 399.69% |
| [1, 2) | 46,187 | 31.247 | 3.2787 | 115.27% |
| [2, 5) | 140,666 | 4.436 | 0.8916 | 20.65% |
| [5, 24] | 297,010 | 1.088 | 0.2452 | 2.42% |

The worst row is a 26,050 CE with 0.0027 days left: the derivative says $-90.6875$ where the
contract is worth $0.05$ and the benchmark says $-0.0500$. This is the failure mode ADR-0001
exists to catch, so the notebook computes the analytic form, prints it beside the repricing one
and **asserts that it disagrees** — at both scales.

### A structure

$$G \;=\; \sum_{i=1}^{n} d_i \, q_i \, g_i$$

The same sum as §2's payoff, $\Pi = L \sum_i d_i q_i (V_i - p_i)$, over a different quantity —
and without the $L$, which is the one place the two identities part company. Every Greek is
**extensive**, so the total is a plain weighted sum with no special cases, and a short leg reports
the negated Greek of the equivalent long leg because $d_i = -1$ is the only difference.

One consequence is the argument for a per-leg breakdown existing at all. The iron condor's net
delta is $-0.0177$, near enough to flat that the payoff chart says nothing about it, while its
individual legs carry $-0.3705$ and $+0.3477$ — twenty times the total, in both directions.

### Verification, and the error against the benchmark

Two of the four are expected to differ from the benchmark, so the useful question is whether they
differ by **exactly** what the convention predicts. An unexplained residual on $\Delta$ would be a
real error; a residual of exactly $1 - D$ is a relabelling.

At the 12:00 snapshot, 55 gradeable legs, with $\hat F$ and $D$ from §1's fit and $\sigma$ from
§4's solve — nothing pre-solved fed in:

| greek | worst abs error | worst rel error | convention | residual |
|---|---|---|---|---|
| $\Delta$ | $5.1441 \times 10^{-3}$ | 0.6520% | $\times\,D$ | $3.5 \times 10^{-12}$ |
| $\Gamma$ | $3.0982 \times 10^{-6}$ | 0.6520% | $\times\,D$ | $5.9 \times 10^{-15}$ |
| $\nu$ | $3.8915 \times 10^{-10}$ | 0.0000% | none | $3.9 \times 10^{-10}$ |
| $\Theta$ | $4.1332 \times 10^{-10}$ | 0.0000% | none | $4.1 \times 10^{-10}$ |

Fifty-five legs at one instant cannot distinguish "right" from "right here", so the same grade
runs over the whole of `Data/greeks.parquet` — **517,672 rows, 8,356 timestamps, 0.0027 to 24.00
days to expiry**. Every row ships the forward, the discount and the volatility that produced its
own Greeks, so the core is fed exactly what it wants and a gap is mathematics rather than
plumbing; `tests/test_oracle.py` takes the same line. The Greek columns stay on the right-hand
side of the subtraction — a test oracle, never an input.

| greek | worst abs | mean abs | median rel | residual after the convention |
|---|---|---|---|---|
| $\Delta$ | $1.3765 \times 10^{-2}$ | $9.0970 \times 10^{-4}$ | 0.270% | $2.2 \times 10^{-16}$ |
| $\Gamma$ | $9.0503 \times 10^{-6}$ | $1.0718 \times 10^{-6}$ | 0.270% | $2.1 \times 10^{-17}$ |
| $\nu$ | $1.7764 \times 10^{-14}$ | $3.5887 \times 10^{-16}$ | 0.000% | $1.8 \times 10^{-14}$ |
| $\Theta$ | $4.1712 \times 10^{-8}$ | $6.2354 \times 10^{-11}$ | 0.000% | $4.2 \times 10^{-8}$ |

All four reduce. $\Delta$ and $\Gamma$ are the benchmark's numbers multiplied by the discount
factor on **every one of the 517,672 rows**; $\nu$ and $\Theta$ need nothing undone. $D$ runs from
0.982269 to 1.000000 across the file, so the gap the convention opens on $\Delta$ reaches
**1.77%** of the figure — large enough to matter and small enough to look like rounding, which is
why it is asserted rather than eyeballed.

#### The synthetic forward

One check grades something no row-by-row comparison can. Long the 25,200 call and short the
25,200 put is a forward outright by put-call parity, so all four exposures follow in closed form
from no Greek formula at all:

```
delta    0.99347998   = D          D N(d1) - D(N(d1) - 1)
gamma    0                         identical for the two legs, cancels
vega     0                         identical for the two legs, cancels
theta    0.01176764                = 19.002881 - 18.991113
                                   = (D_next - D)(F_hat - K)
```

$\Delta$ is exactly $D$, not 1: a forward outright is worth a **discounted** point per point,
which is the content of the convention adopted for the three derivatives. That $\Theta$ is **pure
re-discounting**: the position holds $\hat F - K = 19.12$ points of intrinsic value, one day
nearer, at $r = 15.61\%$, with no volatility term. The check passes only if $\Delta$, $\Gamma$,
$\nu$ and the discount roll are simultaneously right, so a model that is merely self-consistent
does not survive it.

### Exposure across the forward

The notebook sweeps $\hat F$ across §3's window and re-prices, at `dte_days` of 10.56, 5.00, 2.00
and 0.50, so exposure can be read as a shape and its evolution toward expiry on one pair of axes.
Two things are held fixed, and both are assumptions:

- **$\sigma$ is sticky per strike.** Each strike keeps the volatility §4 solved for it; moving the
  forward does not re-solve the smile.
- **$r$ is held at the fitted 15.61%**, so $D(T) = e^{-rT}$ — the same roll $\Theta$ uses one
  session at a time, which makes the curves and the $\Theta$ figures agree by construction.

The family stops at half a day, not zero. The Greeks are undefined at expiry and the core raises
there rather than returning a `NaN`: $\Gamma$ divides by a time-scaling that is zero, and $\Theta$
is the change over a session that no longer exists. The *price* at $T = 0$ is well defined — it is
the expiry line §2 derives — and this is exactly where the payoff and the exposure part company.

| | Long Straddle at $\hat F$ | | | Iron Condor at $\hat F$ | |
|---|---|---|---|---|---|
| `dte_days` | $\Gamma$ | $\nu$ | $\Theta$ | $\Gamma$ | $\Theta$ |
| 10.56 | 0.0009336 | 40.891 | −32.2121 | −0.0001570 | +4.6882 |
| 5.00 | 0.0013612 | 28.228 | −48.7144 | −0.0003927 | +13.9887 |
| 2.00 | 0.0021546 | 17.873 | −85.8503 | −0.0009659 | +38.7264 |
| 0.50 | 0.0042959 | 8.909 | −128.8674 | −0.0011343 | +7.9783 |

The straddle's $\Gamma$ multiplies by 4.60 while its $\nu$ falls to 22% of where it started: the
same position, bought as an opinion about $\sigma$, becomes an opinion about where the index
closes.

The condor's $\Theta$ is **not monotone** — a finer ladder puts the peak at **1.51 days (43.25)**,
falling to **0.01** by a tenth of a day, because a structure sitting between its short strikes has
already converged on its maximum profit and has nothing left to decay. The turnover is also a
property of $\Theta$ being a repricing: a difference quotient over a session is capped by what the
position is worth, so it must fall to zero as the position converges.

Finally, $\Delta$ is bounded by $D(T)\sum q_i$ rather than by $\sum q_i$, and the notebook asserts
the tighter bound at all 400 grid points of all four curves for all 13 structures. Because
$D \to 1$ as $T \to 0$, the bound closes onto $\sum q_i$ exactly as the curves flatten onto it.

### What is still open

Both questions below remain unsettled. What changed is their **scope**: neither blocks Greeks at
the observed moment, and neither blocks the forward-swept charts.

- Spot-to-forward conversion — pricing at a hypothetical spot needs a rule mapping
  $S \to F$, and the data cannot referee it.
  [#13](https://github.com/lalitkarthik/convex-hedge-payoff/issues/13)
  This section never converts one: its x-axis is $\hat F$ itself. The constant-basis convention
  adopted in §2 is a **charting** choice for the expiry line, and is not an answer to this — a
  settled chart axis is not a settled pricing rule.
- Volatility on a target date — whether implied vol is held constant.
  [#8](https://github.com/lalitkarthik/convex-hedge-payoff/issues/8)
  The DTE family above is an *exposure diagnostic* under a named sticky-strike assumption, not a
  P&L curve valued on a future date. Adopting it is not adopting an answer to this.

A third belongs with them, and #27 will have to settle it: **whether a Greeks table should report
the discounted $\Delta$ and $\Gamma$ or the benchmark's undiscounted ones.** This file reports the
discounted forms because they are the derivatives of the price it computes; the benchmark reports
the undiscounted ones because that is the market convention. The measurement above says the two
are one multiplication apart and never more, which is the input to that decision rather than the
decision.

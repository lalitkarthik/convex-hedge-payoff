# NIFTY Options Payoff Engine

The shared vocabulary for this repository. Two developers build against one interface, and
several of these words are genuinely ambiguous in the wild — "payoff" and "P&L" are used
interchangeably by most trading platforms, and "forward" and "futures price" are treated as
synonyms. They are not synonyms here.

This file is a glossary and nothing else. It records what a word *means*, never how a thing is
built. Design decisions live in the issues; architectural ones live in `docs/adr/`.

## The underlying

**Spot**:
The NIFTY 50 index level. The unit of the payoff chart's x-axis, and the only price a user
ever reads or types.
_Avoid_: Underlying price, index price, cash price

**Forward**:
The break-even future price of the index implied by the option chain itself, for a given
expiry. This is the price the pricing model consumes; Spot is not. It is derived from the
chain, not observed, and on a thin chain it may not be recoverable at all.
_Avoid_: Futures price, fair value, synthetic future

**Basis**:
Forward minus Spot. Widest when Expiry is distant and converges to zero as Expiry arrives.

**Discount Factor**:
The factor that converts a value at expiry into a value today. Recovered from the chain
alongside the Forward, and equal to 1 at expiry.
_Avoid_: Present value factor, DF

A **futures price** — the price of an exchange-traded NIFTY futures contract — is deliberately
*not* a term in this project. No futures series exists in the data, so any use of the word
would be an assumption dressed as an observation.

## Time

**Expiry**:
The date on which the contracts settle and all optionality disappears. For NIFTY index options
this is European and cash-settled; there is no early exercise.

**Target Date**:
A user-chosen date strictly before Expiry, at which the strategy is valued "as if today were
then". Expiry is the special case of a Target Date with no time left, not a separate concept.
_Avoid_: Valuation date, as-of date

## Structure

**Leg**:
A single option contract within a Strategy: its strike, its type (call or put), its direction
(bought or sold), its Quantity, the price it was entered at, and its implied volatility. A Leg
does **not** know its Lot Size.
_Avoid_: Position (see below), contract, trade

**Quantity**:
How many of a Leg were traded, carried on the Leg itself. Direction is separate from Quantity —
a Leg is never held as a negative quantity.

**Lot Size**:
The exchange-mandated number of index units per contract. Currently 65 for NIFTY. It is a
multiplier applied when results are presented, never a property stored on a Leg, because the
exchange revises it and every stored Leg would be silently wrong the day it changes.
_Avoid_: Contract size, multiplier

**Strategy**:
An ordered list of Legs. Nothing more. "Iron condor" is not a kind of Strategy — it is a shape
that a list of four Legs happens to have, and every metric in this project is computed from the
list without knowing or caring what the shape is called.
_Avoid_: Spread, combination, structure

**Preset**:
A convenience that builds a well-known list of Legs — "long straddle", "iron condor" — so the
user does not have to pick each Leg by hand. A Preset produces a Strategy; it is not a type of
Strategy, and adding one adds no capability to the engine.
_Avoid_: Template, strategy type, builder

**Strategy Label**:
The human name inferred *from* a list of Legs by recognising its shape, as when a screen reads
"2 selected — Long Straddle". Detection runs after the fact and is purely descriptive; a
Strategy is valid and fully computable whether or not it matches any known shape.

## Results

**Payoff**:
The terminal value of a Strategy's Legs at Expiry, ignoring what was paid for them. Premium-blind.
_Avoid_: Return, terminal P&L

**P&L**:
Payoff-style value minus the Entry Premium — what actually lands in the account. Evaluated at
any time, not only at Expiry.

Both lines on the chart are P&L, not Payoff. The distinction matters because the two are one
subtraction apart and the code will carry a function for each.

**Entry Premium**:
The price a Leg was opened at. Per Leg, signed by direction.
_Avoid_: Cost, LTP, entry price

**Net Premium**:
The Entry Premiums of every Leg in a Strategy, summed with direction. Positive means paid out
(a debit); negative means received (a credit).
_Avoid_: Cost of the strategy, net cost

**Unbounded**:
The state of a maximum profit or maximum loss that has no finite value, shown to a user as
"Unlimited". Either can be Unbounded, but only ever through the right-hand tail: the left-hand
tail always terminates, because Spot cannot fall below zero.
_Avoid_: Unlimited (in code), infinite, None

## Data

**Chain**:
Every option quoted for one expiry at one moment: both types, all strikes.
_Avoid_: Option chain snapshot, book

**Oracle**:
The pre-solved volatilities and Greeks shipped with the dataset. It is a *test fixture*, never
an input — the engine computes these values itself and is asserted against the Oracle. If the
engine ever reads the Oracle to produce an answer, the point of the project has been lost.
_Avoid_: Reference data, ground truth, precomputed Greeks

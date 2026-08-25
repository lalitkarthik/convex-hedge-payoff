"""The seam: the shared types both halves of the codebase build against.

#23 puts this module before everything else, and it is the one file where a merge
conflict is a symptom rather than an accident (CONTRIBUTING.md, #11). It holds types
and nothing else - no maths, no I/O, no lookups.

The vocabulary is `CONTEXT.md`'s, deliberately: the words that are ambiguous in the
wild are pinned here so the two halves cannot mean different things by them.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

OptionType = Literal["CE", "PE"]
"""Call or put, in the notation the dataset itself uses."""

Direction = Literal[1, -1]
"""Bought or sold. Separate from Quantity, so a Leg is never held at a negative
quantity (CONTEXT.md) - the two encodings would produce the same curve today and
disagree the first time anything sums or displays Quantity."""

Quantity = Annotated[int, Field(ge=1)]
"""How many of a Leg were traded. At least one; the sign lives in Direction."""

ForwardMethod = Literal["parity_fit", "single_strike_parity", "spot"]
"""How a moment's Forward was arrived at (#51).

The regression over both-sided strikes is trustworthy on 316 of the sample day's 376
minutes. `single_strike_parity` inverts parity at one strike with the rate assumed at
6.5%; `spot` means nothing quoted both sides at the money and there was nothing better
than Spot itself. Published rather than inferred, because the three are indistinguishable
by inspection and only the first is measured."""

Finite = Annotated[float, Field(allow_inf_nan=False)]
"""A real number, and nothing else.

ADR-0001 bans NaN in the core and the API contract bans it on the wire; enforcing it
on the type means it cannot reach the wire however the layers above are rewritten. An
infinity is banned with it - Unbounded is `None`, which is a different thing.
"""

Unbounded = Finite | None
"""A maximum that may have no finite value. `None` serialises as JSON `null` and is
shown to a trader as "Unlimited" (CONTEXT.md); it is never an infinity token and never
a string."""


class LegRequest(BaseModel):
    """A Leg as a client is allowed to describe it.

    Deliberately narrower than a `Leg`: there is no implied volatility here, because
    the server looks it up (#23). A wrong volatility does not fail loudly - it produces
    a plausible chart that nothing downstream would catch - so the field does not exist
    to be got wrong, and unknown fields are rejected rather than ignored.

    Entry Premium is the one price a trader may legitimately supply (story 18, "what if
    I had entered at X"). Absent, the Chain's last traded price is used.
    """

    model_config = ConfigDict(extra="forbid")

    strike: float
    option_type: OptionType
    direction: Direction
    quantity: Quantity = 1
    entry_premium: float | None = None


class Leg(BaseModel):
    """A single option contract within a Strategy.

    Strike, type, direction, Quantity, the price it was entered at, and its implied
    volatility - and **not** its Lot Size. Lot Size is a multiplier applied when
    results are presented, never a property stored here, because the exchange revises
    it and every stored Leg would be silently wrong the day it changes (CONTEXT.md).
    """

    strike: float
    option_type: OptionType
    direction: Direction
    quantity: Quantity
    entry_premium: float
    iv: float


class AnalysisRequest(BaseModel):
    """Analyse one Strategy, as-of one moment.

    There is no Strategy type: a Strategy is an ordered list of Legs and nothing more
    (CONTEXT.md). The order is the order the trader built them in, and it is preserved
    because the per-Leg Greeks table (#27) is read alongside the Legs on screen.

    The moment is what the whole response is served as-of - the Chain, the Entry
    Premiums and the volatilities all come from it, so it is asked for once here rather
    than per Leg.
    """

    model_config = ConfigDict(extra="forbid")

    moment: str
    legs: list[LegRequest]


class Metrics(BaseModel):
    """The four numbers under the chart, plus the ratio between two of them.

    Every one of them is a property of the Legs at Expiry. Net Premium is signed the
    way CONTEXT.md signs it: positive is paid out (a debit), negative is received (a
    credit).
    """

    max_profit: Unbounded
    max_loss: Unbounded
    breakevens: list[Finite]
    net_premium: Finite
    reward_risk: Unbounded
    """Max Profit over the magnitude of Max Loss. `None` when either side is Unbounded
    or when there is no loss to divide by - a ratio against Unlimited has no meaning,
    and publishing a large number instead would read as a good trade."""


class Curve(BaseModel):
    """The chart's line: P&L at Expiry across a range of Spot values.

    Two parallel arrays, as the prototype in #9 published them and as a chart consumes
    them. Both lines a trader sees are P&L rather than Payoff (CONTEXT.md) - Payoff is
    premium-blind and is one subtraction away.
    """

    spot: list[Finite]
    pnl_at_expiry: list[Finite]

    @model_validator(mode="after")
    def _same_length(self) -> "Curve":
        """Parallel arrays that disagree do not raise on a chart - they draw, slightly
        wrong, and nobody notices. So they cannot be built that way."""
        if len(self.spot) != len(self.pnl_at_expiry):
            raise ValueError("a curve needs one P&L for every Spot")
        return self


class AnalysisResponse(BaseModel):
    """Everything about one Strategy, in one response.

    Deliberately fat (#23). Splitting it would mean several round trips carrying the
    same Legs and recomputing the same curve, and the trader would watch the numbers
    arrive after the chart they belong to. #27 and #29 add the Greeks and the Payoff
    Table to this same response rather than to endpoints of their own.
    """

    moment: str
    spot: Finite
    """The NIFTY level at the moment - what the header shows and the x-axis measures."""

    curve: Curve
    metrics: Metrics


class ChainQuote(BaseModel):
    """One side of one strike, as of a moment.

    There is no implied volatility here. It is a property of the strike and is carried
    once on the row, not once per side (#28).
    """

    last: Finite
    open_interest: Finite
    volume: Finite
    age_minutes: int = Field(ge=0)
    """How stale this bar is, in whole minutes. A quote is never from the future, and
    bars are one minute wide. #31 dims on it; this is where it is emitted."""

    delta: Finite
    """Per side, and genuinely so: a call and its put at one strike have deltas one
    apart rather than equal. That is the opposite of implied volatility, and the two
    are easy to conflate."""


class ChainRow(BaseModel):
    """One strike: calls on the left, puts on the right, the strike down the middle.

    Either side may be absent. Only strikes that actually traded in a minute have a
    bar, and served as-of a strike may have been quoted on one side only.
    """

    strike: Finite
    iv: Finite | None = None
    """One implied volatility for the strike, from its freshest quote - not one per
    side. Served as-of, a call and its put can be minutes apart and quote genuinely
    different volatilities; publishing both would contradict the model that produced
    them (#28)."""

    call: ChainQuote | None = None
    put: ChainQuote | None = None


class ChainResponse(BaseModel):
    """The Chain a trader browses, as-of one moment."""

    moment: str
    spot: Finite
    expiry: str
    """Text, not a dropdown: the dataset holds exactly one Expiry, which is why a
    calendar or a diagonal has no second Leg to reference and is unbuildable here
    rather than merely deprioritised."""

    forward: Finite
    """The Forward this moment implies, fitted from the quotes themselves (#51).

    Not read from the file. `CONTEXT.md:138` - the engine that reads the Oracle to
    produce an answer has lost the point of the project - so `chain.load_chain()` drops
    the column outright and this number is recovered from put-call parity instead."""

    discount: Finite
    """The Discount Factor for the same moment, recovered alongside the Forward from the
    same fit. Never a rate: ADR-0001 keeps the rate out of every interface."""

    forward_method: ForwardMethod
    """Which tier of the ladder answered. On 60 of the sample day's 376 minutes the
    regression cannot be trusted and the Forward is assumed rather than measured - and an
    assumed number that cannot be told apart from a measured one is exactly the failure
    ADR-0001 exists to catch."""

    rows: list[ChainRow]


class PresetResponse(BaseModel):
    """What the picker offers, and what one of them builds.

    The Legs come back as **requests**, not as resolved Legs: a Preset hands the client
    exactly what a trader would have picked by hand, and it goes back through the same
    endpoint. That is what makes "analysing a Preset" and "selecting its Legs by hand"
    the same operation rather than two paths that agree.
    """

    presets: list[str]
    legs: list[LegRequest] = []

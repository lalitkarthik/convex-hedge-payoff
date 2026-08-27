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

ExpiryLabel = str
"""An Expiry, spelled the one way the wire spells it: `10FEB26` (#68, #71).

The same text `ChainResponse.expiry` echoes, `SessionResponse.expiry` names, the dropdown
renders, the URL carries and `/chain` accepts - so a client compares what it asked for
against what it got without a conversion in the middle.

Left as plain text rather than pinned to a pattern here. `catalog.parse_label` is what
reads one, and it says `cannot read "10FEV26" as an Expiry; the form is 10FEB26`, which
a regular expression in the schema would replace with the regular expression.
"""


class LegRequest(BaseModel):
    """A Leg as a client is allowed to describe it.

    Deliberately narrower than a `Leg`: there is no implied volatility here, because
    the server looks it up (#23). A wrong volatility does not fail loudly - it produces
    a plausible chart that nothing downstream would catch - so the field does not exist
    to be got wrong, and unknown fields are rejected rather than ignored.

    Entry Premium is the one price a trader may legitimately supply (story 18, "what if
    I had entered at X"). Absent, the Chain's last traded price is used.

    **The Expiry is carried here and is required** (#71). A strike and a side do not name
    a contract once more than one series trades - 25200 CE is a different instrument in
    each of them - so a Leg described without one is ambiguous the moment the store holds
    a second Expiry, and an ambiguity resolved by a default is one nobody sees resolved.
    The request no longer carries a single Expiry for the whole Strategy: this is the
    smaller schema, and it is what a calendar structure will eventually need.
    """

    model_config = ConfigDict(extra="forbid")

    strike: float
    option_type: OptionType
    expiry: ExpiryLabel
    direction: Direction
    quantity: Quantity = 1
    entry_premium: float | None = None


class Leg(BaseModel):
    """A single option contract within a Strategy.

    Strike, type, **Expiry**, direction, Quantity, the price it was entered at, and its
    implied volatility - and **not** its Lot Size. Lot Size is a multiplier applied when
    results are presented, never a property stored here, because the exchange revises
    it and every stored Leg would be silently wrong the day it changes (CONTEXT.md).

    The Expiry survives resolution rather than being consumed by it (#71): the strike and
    the side alone do not say which contract was priced, and a resolved Leg that had
    forgotten its series could not be told apart from one in another.
    """

    strike: float
    option_type: OptionType
    expiry: ExpiryLabel
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

    **The Expiry is the other way round** (#71). It is a property of each Leg and not of
    the request, because a moment is one thing a Strategy is looked at from and an Expiry
    is one thing each contract in it has. Nothing here restates it, so nothing here can
    contradict a Leg.

    A Strategy whose Legs span more than one Expiry is **refused** - see
    `strategy.sole_expiry`. Not refused here: the rule is about what can be drawn rather
    than about what can be typed, and `strategy.MixedExpiry` says which two series were
    named where a validation envelope would say `body -> legs`.
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


class LegGreeks(BaseModel):
    """One Leg's exposures, or a whole Strategy's - the shape is the same either way.

    **Per contract**: no Lot Size and no number of lots. Those are presentation
    multipliers (#29) and a Greek that carried them could not be compared against
    another Strategy's. The per-Leg rows *are* signed by Direction and Quantity, because
    that is what a per-Leg exposure row means to whoever reads it beside the Legs.

    Conventions are stated once, in `pricing.black76_greeks`. One of them surprises:
    **theta is a one-session repricing** rather than the analytic derivative. Delta and
    gamma are **undiscounted**, which is the Oracle's convention and the ordinary one.
    """

    delta: Finite
    """Rupees per point of **forward**, never of spot. Undiscounted, so bounded by
    `[0, 1]` for a call and `[-1, 0]` for a put, and a call's delta and its put's differ
    by exactly 1 at every strike."""

    gamma: Finite
    """Delta per point. Two orders of magnitude smaller than the rest at this expiry."""

    vega: Finite
    """Per volatility **point** - a 1% move, not a move from 0.16 to 1.16."""

    theta: Finite
    """Per trading **session**, already scaled: do not divide by 252 again. Negative for a
    long option, and bounded by the premium, which the analytic form is not."""

    rho: Finite
    """Per one percent."""


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

    forward: Finite
    """The Forward the Greeks were priced at, fitted from the quotes (#51). Published
    because a delta is meaningless without the underlying it is a slope against, and the
    basis reaches +118.87 - the number is not spot."""

    discount: Finite
    """The Discount Factor from the same fit. Delta and gamma carry it (#53)."""

    curve: Curve
    metrics: Metrics

    table: Curve = Curve(spot=[], pnl_at_expiry=[])
    """The Payoff Table (#29): the same P&L at Expiry, on the 50-point grid a trader
    reads, rather than the 400-point one the chart draws.

    The same `Curve` type as the chart deliberately - it is the same quantity sampled
    twice, not two quantities, and the two must agree wherever they share a Spot. A type
    of its own would invite them to drift."""

    greeks: list[LegGreeks] = []
    """One row per Leg, in the order the Legs were sent - the Greeks table is read
    beside them on screen (#27)."""

    total_greeks: LegGreeks | None = None
    """The Strategy's exposure: `G = sum_i d_i q_i g_i`, with no branching on Leg count
    and none on Strategy name. `None` only when there are no Legs to sum."""


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

    delta: Finite | None = None
    """Per side, and genuinely so: a call and its put at one strike have deltas one
    apart rather than equal. That is the opposite of implied volatility, and the two
    are easy to conflate.

    Nullable for the same reason `ChainRow.iv` is, and always together with it: a delta
    is priced at the strike's implied volatility, so a print that no volatility
    reproduces has no delta either. Fabricating one would be worse than admitting it -
    it is a number a trader would size a position against. Rare, and only away from the
    anchor: 2 of 7 January's 244 bars and 58 of 10 February's 45,330."""


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

    Not read from the source file. `CONTEXT.md:138` - the engine that reads the Oracle
    to produce an answer has lost the point of the project - so the build never opens the
    file that carries it, and this number is recovered from put-call parity instead, in
    the build that writes the store (#66, #67)."""

    discount: Finite
    """The Discount Factor for the same moment, recovered alongside the Forward from the
    same fit. Never a rate: ADR-0001 keeps the rate out of every interface."""

    forward_method: ForwardMethod
    """Which tier of the ladder answered. On 60 of the sample day's 376 minutes the
    regression cannot be trusted and the Forward is assumed rather than measured - and an
    assumed number that cannot be told apart from a measured one is exactly the failure
    ADR-0001 exists to catch."""

    rows: list[ChainRow]


class SummaryResponse(BaseModel):
    """The header, at one minute - and nothing about any strike (#69).

    Spot, the Forward, the Discount Factor and the at-the-money volatility are facts about
    the **minute**. In the stored Chain they repeat across every strike of that minute, so
    a header that read them there opened the largest artifact in the tree to take four
    numbers out of about 196 identical copies of each. They are stored once instead, one
    row a minute, and this is that row on the wire.

    Dragging the time control moves the header 375 times across a session. Every one of
    those was a read of the Chain and is now a lookup.

    **Every figure here is the one `/chain` publishes for the same minute.** That is not a
    coincidence to be checked occasionally, it is the reason the split is safe: the build
    reduces the Chain frame it is about to write, so there is no second derivation that
    could drift. Two artifacts describing one minute that can disagree would be worse than
    one artifact.
    """

    moment: str
    """Echoed back as it was asked for, exactly as `ChainResponse.moment` is - a client
    that compares the two must find them equal on both endpoints or on neither."""

    date: str
    expiry: str
    """The pair this row belongs to, spelled as `/session` and `/chain` spell them."""

    spot: Finite
    forward: Finite
    discount: Finite
    forward_method: ForwardMethod
    """The same four the Chain carries, from the same minute and the same fit."""

    atm_strike: Finite
    """The quoted strike nearest the **Forward** - not nearest Spot. The basis reaches
    +118.87 at the anchor, more than two 50-point intervals, so the two anchors pick
    different strikes. Published because the volatility below is meaningless without the
    strike it belongs to."""

    atm_iv: Finite | None = None
    """That strike's implied volatility, by the same rule `ChainRow.iv` follows: one per
    strike, from its freshest quote.

    Nullable for the reason `ChainRow.iv` is nullable - a print that no volatility
    reproduces has none, and every strike in the last minute of Expiry day is such a
    print. `None` is the honest answer where a fabricated number would be read as one."""


class SessionResponse(BaseModel):
    """What a client needs before it can ask for anything else.

    Every other endpoint takes a `moment`, and until this existed there was no way to
    learn which moments there are. The frontend held the list in a generated fixture
    instead, which made the set of tradeable minutes a property of a build script rather
    than of the data - and free to drift from it silently.

    Bounds and counts as well as the list itself, because a slider needs its ends and a
    trader reading "376" learns something the array does not tell them at a glance.

    A session is **one date and one Expiry** (#68), and it carries the two lists a client
    picks the next one from. That is what makes the dropdowns above the Chain open
    without reading a data file, and it is the same argument as the paragraph above: a
    list of dates written by a build script is a list that can drift from the tree the
    engine will actually serve.

    `date` and `expiry` name the pair this response describes, and they are **not
    necessarily the pair that was asked for**. A request naming a date and an Expiry that
    date did not trade is resolved to one that exists rather than refused, so a client
    renders these two fields rather than what it sent.
    """

    date: str
    """The trading date this session describes, ISO 8601, as `/chain` accepts it."""

    dates: list[str]
    """Every trading date in the store, ascending. What the date dropdown lists.

    Off the manifest rather than off a directory walk or a clock: it is the index over
    the partitions, and it is written last by the build so it cannot advertise a day that
    is no longer stored."""

    moments: list[str]
    """Every minute that quoted, in session order, spelled as `/chain` accepts it.

    Derived from the data and never from a clock: a minute in which nothing traded has
    no bar, and offering it as a stop would return an empty Chain."""

    moment_count: int = Field(ge=1)
    first_moment: str
    last_moment: str

    expiry: str
    """The Expiry this session describes, spelled as `ChainResponse.expiry` spells it -
    `10FEB26` - so a client can compare the two without a conversion in the middle."""

    expiries: list[str]
    """Every Expiry that traded on `date`, ascending. What the Expiry dropdown lists.

    Only the ones that traded **that day**, which is the point: a dropdown offering a
    pair the store does not hold fails at the moment a trader clicks, three screens from
    the code that offered it. One Expiry exists in this dataset, so this has one entry;
    nothing that produces or consumes it is allowed to assume that."""

    strike_min: Finite
    strike_max: Finite
    """The **day's** range, not a minute's. An axis that resized as the trader moved
    through time would make two charts of the same Strategy incomparable."""

    presets: list[str]
    """The names the picker offers, and the names `/presets/{name}` will build."""


class PresetResponse(BaseModel):
    """What the picker offers, and what one of them builds.

    The Legs come back as **requests**, not as resolved Legs: a Preset hands the client
    exactly what a trader would have picked by hand, and it goes back through the same
    endpoint. That is what makes "analysing a Preset" and "selecting its Legs by hand"
    the same operation rather than two paths that agree.
    """

    presets: list[str]
    legs: list[LegRequest] = []

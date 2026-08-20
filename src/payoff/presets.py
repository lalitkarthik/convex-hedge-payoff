"""Presets: five functions that each return a list of Legs.

**This module adds no capability to the engine, and that is the point** (#30). A Preset
produces a Strategy; it is not a kind of Strategy (CONTEXT.md). "Iron condor" is not a
type here - it is a shape that a list of four Legs happens to have, and every metric is
computed without knowing or caring what the shape is called.

So there is no Strategy type, no shape validator and no branching on leg count anywhere
below this module. A trader can edit a Preset's Legs afterwards like any others and the
result simply stops matching the Preset, because nothing stores "this is an iron
condor".

The reverse direction - inferring a **Strategy Label** *from* a list of Legs, as in
"2 selected - Long Straddle" - is a different and deliberately deferred concept (#23).
A Preset goes Legs-outward; a Label goes Legs-inward. Building the second while
building the first is how a shape name ends up load-bearing.
"""

from payoff.models import LegRequest

PRESETS = ("straddle", "strangle", "iron_condor", "credit_spread", "iron_fly")
"""The picker's short list. Naked Legs are not here: one Leg is one click already."""


DEFAULT_WIDTH = 200.0
"""How far a Preset's outer Legs sit from its centre, in points.

Four strikes on this chain's 50-point grid. Wide enough that a condor has a body worth
looking at, narrow enough that its wings are still liquid.
"""


class UnknownPreset(LookupError):
    """A name the picker does not offer."""


def straddle(centre: float, width: float, direction: int) -> list[LegRequest]:
    """A call and a put at the same strike.

    Bought, it costs the two premiums and needs a move of that size in either direction
    to break even; sold, it receives them and keeps them if nothing happens.
    """
    return [
        LegRequest(strike=centre, option_type=option_type, direction=direction)
        for option_type in ("CE", "PE")
    ]


def strangle(centre: float, width: float, direction: int) -> list[LegRequest]:
    """A straddle spread apart: the call above the money, the put below it.

    Cheaper than a straddle and needs a bigger move, which is the trade-off. Both
    Breakevens sit outside the two strikes, because between them both Legs expire
    worthless.
    """
    return [
        LegRequest(strike=centre + width, option_type="CE", direction=direction),
        LegRequest(strike=centre - width, option_type="PE", direction=direction),
    ]


def credit_spread(centre: float, width: float, direction: int) -> list[LegRequest]:
    """Sell a put, buy a further one below it: paid up front, loss bounded.

    The one directional Preset here, and the bullish one - it profits while Spot stays
    above the sold strike. Its payoff crosses zero exactly once, which is what makes it
    a view on direction rather than on movement. `direction` is ignored for the reason
    it is on the condor: reversing the signs is a debit spread, a different trade.
    """
    return [
        LegRequest(strike=centre, option_type="PE", direction=-1),
        LegRequest(strike=centre - width, option_type="PE", direction=1),
    ]


def iron_condor(centre: float, width: float, direction: int) -> list[LegRequest]:
    """Sell a strangle, buy a wider one around it.

    A bet that Expiry lands inside the body, with the bought wings turning what would
    otherwise be an Unbounded loss into a known one. `direction` is ignored: the
    structure is defined by its own internal signs, and reversing them produces a long
    condor, which is a different trade rather than the same one held the other way.
    """
    return [
        LegRequest(strike=centre - width, option_type="PE", direction=-1),
        LegRequest(strike=centre - 2 * width, option_type="PE", direction=1),
        LegRequest(strike=centre + width, option_type="CE", direction=-1),
        LegRequest(strike=centre + 2 * width, option_type="CE", direction=1),
    ]


def iron_fly(centre: float, width: float, direction: int) -> list[LegRequest]:
    """A short straddle with wings bought: the condor's body squeezed to a point.

    It collects more than the condor at the same width, because a sold straddle
    collects more than a sold strangle, and it keeps it over a narrower range. That
    trade - more premium for less room - is the whole difference between the two.
    """
    return [
        LegRequest(strike=centre, option_type="CE", direction=-1),
        LegRequest(strike=centre, option_type="PE", direction=-1),
        LegRequest(strike=centre + width, option_type="CE", direction=1),
        LegRequest(strike=centre - width, option_type="PE", direction=1),
    ]


BUILDERS = {
    "straddle": straddle,
    "strangle": strangle,
    "iron_condor": iron_condor,
    "credit_spread": credit_spread,
    "iron_fly": iron_fly,
}
"""Name to builder. A dict rather than a chain of ifs, because adding a Preset should
be adding a function - if it ever means editing a branch, the shape has become
load-bearing.
"""


def build(
    name: str,
    centre: float,
    *,
    width: float = DEFAULT_WIDTH,
    direction: int = 1,
) -> list[LegRequest]:
    """The Legs a Preset would have had a trader pick by hand."""
    if name not in BUILDERS:
        raise UnknownPreset(name)
    return BUILDERS[name](centre, width, direction)

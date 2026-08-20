"""Chain loading and the as-of view.

Runtime data is **one derived file loaded into memory at boot** - not the three raw
files, and not a database (#23). The file is `Data/sample/chain_2026-01-27.parquet`,
which is already the product of the IST/UTC join documented in `docs/data-quality.md`.
Widening it beyond one day is a matter of regenerating that file; nothing in this
module's interface changes.

**The Chain is served as-of.** Only strikes that actually traded in a given minute have
a bar, so a strict reading of "the Chain at this moment" is much thinner than a trader
expects - the last known quote at or before the moment is what makes a usable chain.
#28 owns the shape that view is published in, and the measurements behind it.

The core never sees a Chain. A strike absent from it raises **here** (#23).
"""

from functools import lru_cache
from pathlib import Path

import pandas as pd

from payoff.models import Leg, LegRequest

RUNTIME_FILE = Path(__file__).resolve().parents[2] / "Data" / "sample" / "chain_2026-01-27.parquet"


class StrikeNotQuoted(LookupError):
    """A strike with no quote at or before the requested moment.

    Carries the strike so the interface can name it rather than showing a blank chart.
    #31 owns what a caller sees when this happens.
    """

    def __init__(self, strike: float, option_type: str) -> None:
        self.strike = strike
        self.option_type = option_type
        super().__init__(f"{strike:.0f} {option_type} is not quoted at or before this moment")


@lru_cache(maxsize=1)
def load_chain() -> pd.DataFrame:
    """Load the runtime file once, at boot, and keep it for the process's lifetime."""
    return pd.read_parquet(RUNTIME_FILE).sort_values("ts").reset_index(drop=True)


def snapshot(moment: str | pd.Timestamp) -> pd.DataFrame:
    """The Chain as-of `moment`: the last known quote for every strike at or before it."""
    at_or_before = load_chain()[lambda chain: chain.ts <= pd.Timestamp(moment)]
    return at_or_before.groupby(["strike", "option_type"], as_index=False).last()


def spot_at(moment: str | pd.Timestamp) -> float:
    """The NIFTY level at the moment - what the header shows and the x-axis measures."""
    rows = load_chain()[lambda chain: chain.ts <= pd.Timestamp(moment)]
    if rows.empty:
        raise StrikeNotQuoted(0.0, "--")
    return float(rows.spot.iloc[-1])


def resolve_legs(requests: list[LegRequest], moment: str | pd.Timestamp) -> list[Leg]:
    """Turn what the client asked for into Legs the engine can price.

    This is where implied volatility enters the system - **looked up, never accepted
    from the client**. A client that posted a wrong value would get a plausible-looking
    wrong chart that nothing else would catch.

    Entry Premium is the Chain's last traded price unless the client overrode it
    (story 18), which is the one price a trader legitimately supplies.
    """
    quotes = snapshot(moment).set_index(["strike", "option_type"])

    legs = []
    for request in requests:
        key = (request.strike, request.option_type)
        if key not in quotes.index:
            raise StrikeNotQuoted(request.strike, request.option_type)
        quote = quotes.loc[key]

        legs.append(
            Leg(
                strike=request.strike,
                option_type=request.option_type,
                direction=request.direction,
                quantity=request.quantity,
                entry_premium=(
                    float(quote["last"]) if request.entry_premium is None
                    else float(request.entry_premium)
                ),
                iv=float(quote["iv"]),
            )
        )
    return legs

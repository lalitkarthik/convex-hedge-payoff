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

import numpy as np
import pandas as pd

from payoff import forward as forward_maths
from payoff.models import ChainQuote, ChainResponse, ChainRow, Leg, LegRequest
from payoff.pricing import TRADING_DAYS_PER_YEAR

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


#: Solved upstream and shipped in the file. The engine derives both itself (#51) and is
#: graded against these columns in `tests/test_forward.py`, so they are dropped at load:
#: an answer that cannot be read cannot be read by accident.
ORACLE_COLUMNS = ("forward", "discount")


@lru_cache(maxsize=1)
def load_chain() -> pd.DataFrame:
    """Load the runtime file once, at boot, and keep it for the process's lifetime."""
    chain = pd.read_parquet(RUNTIME_FILE).sort_values("ts").reset_index(drop=True)
    return chain.drop(columns=list(ORACLE_COLUMNS))


@lru_cache(maxsize=512)
def strict_slice(moment: str | pd.Timestamp) -> pd.DataFrame:
    """Every quote stamped at **one** minute - the latest minute at or before `moment`.

    The counterpart to `snapshot()`, and not a substitute for it. A chain is served
    as-of because a strict reading of it is too thin to trade from; a *fit* is run
    strictly because the as-of view mixes quote ages up to 153 minutes apart, and the
    regression's slope is the Discount Factor. Stale prints would land in it directly.
    """
    chain = load_chain()
    stamps = chain.ts[chain.ts <= pd.Timestamp(moment)]
    if stamps.empty:
        raise StrikeNotQuoted(0.0, "--")
    return chain[chain.ts == stamps.iloc[-1]]


def paired_quotes(rows: pd.DataFrame) -> pd.DataFrame:
    """One row per strike quoting **both** sides, with the two prices beside each other.

    Parity is an identity about a call and its put at one strike, so a strike quoting
    only one side has nothing to say and is dropped rather than half-used.
    """
    return (
        rows.pivot_table(index="strike", columns="option_type", values="last")
        .reindex(columns=["CE", "PE"])
        .dropna()
    )


@lru_cache(maxsize=512)
def forward_at(moment: str | pd.Timestamp) -> forward_maths.ForwardFit:
    """The Forward and Discount Factor this moment implies (#51).

    Slices the minute and hands `forward.fit_forward` arrays; the maths never sees a
    chain. The result names the tier that produced it, because on 60 of this day's 376
    minutes the regression cannot be trusted and the answer is assumed rather than
    measured.
    """
    rows = strict_slice(moment)
    paired = paired_quotes(rows)
    return forward_maths.fit_forward(
        strikes=paired.index.to_numpy(float),
        calls=paired.CE.to_numpy(float),
        puts=paired.PE.to_numpy(float),
        quoted_strikes=rows.strike.unique(),
        T=float(rows.dte_days.iloc[0]) / TRADING_DAYS_PER_YEAR,
        spot=float(rows.spot.iloc[0]),
    )


@lru_cache(maxsize=256)
def snapshot(moment: str | pd.Timestamp) -> pd.DataFrame:
    """The Chain as-of `moment`: the last known quote for every strike at or before it.

    Every row carries `age_minutes`. On the sample day the median quote is one minute
    old while the wings reach 153, and presenting the second as live would be dishonest
    rather than merely imprecise.

    Cached per moment: the runtime file is immutable for the life of the process, so
    the same minute cannot produce two different snapshots. Callers treat the frame as
    read-only. Building one costs 5.5 ms - not the 0.258 ms #23 measured for a
    searchsorted index, but still an order of magnitude inside the round trip it saves,
    and the cache takes a repeat to microseconds.
    """
    moment = pd.Timestamp(moment)
    at_or_before = load_chain()[lambda chain: chain.ts <= moment]
    latest = at_or_before.groupby(["strike", "option_type"], as_index=False).last()

    age = (moment - latest.ts).dt.total_seconds() // 60

    # Implied volatility is a property of the STRIKE, not of the side. Served as-of,
    # a call and its put can be minutes apart: of the 41 both-sided strikes at the
    # anchor minute only 9 share a minute, and the rest disagree by up to 0.0275. The
    # one that belongs to the strike is the freshest of the two.
    freshest = latest.sort_values("ts").groupby("strike").iv.last()

    return latest.assign(
        age_minutes=age.astype("int64"),
        strike_iv=latest.strike.map(freshest).astype(float),
    )


def spot_at(moment: str | pd.Timestamp) -> float:
    """The NIFTY level at the moment - what the header shows and the x-axis measures."""
    rows = load_chain()[lambda chain: chain.ts <= pd.Timestamp(moment)]
    if rows.empty:
        raise StrikeNotQuoted(0.0, "--")
    return float(rows.spot.iloc[-1])


def at_the_money(moment: str | pd.Timestamp) -> float:
    """The quoted strike nearest the **Forward** (#51).

    Not nearest Spot. The basis runs to +118.87 at the anchor minute, which is more than
    two 50-point intervals, so the two anchors select different strikes - 25,200 against
    25,100 - and every Preset centred here moves with it. Spot is where the index is; the
    Forward is what the options are priced off, and the money is a fact about the options.

    Nearest **quoted** strike rather than the arithmetic answer rounded to the grid: on a
    thin minute the arithmetic answer may not be quoted at all, and a Preset that opens
    with an unquoted Leg is worse than one that opens a strike away.

    Chosen among strikes quoting both sides, which is the same set the fit ran on. Where
    that set is empty - at the close, nothing quotes both - the choice widens to every
    strike quoted that minute rather than failing: a coarser answer beats none.
    """
    rows = strict_slice(moment)
    paired = paired_quotes(rows)
    candidates = (
        paired.index.to_numpy(float) if len(paired) else np.sort(rows.strike.unique())
    )
    if not len(candidates):
        raise StrikeNotQuoted(0.0, "--")
    return float(candidates[np.abs(candidates - forward_at(moment).forward).argmin()])


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
                iv=float(quote["strike_iv"]),
            )
        )
    return legs


def expiry_label() -> str:
    """The single Expiry this dataset contains, read off the instrument name.

    'NIFTY10FEB2623350PE.NFO' -> '10FEB26'. There is exactly one, which is why the
    header shows text rather than a dropdown.
    """
    ticker = str(load_chain().Ticker.iloc[0])
    return ticker.removeprefix("NIFTY")[:7]


def as_of_view(moment: str | pd.Timestamp) -> ChainResponse:
    """The Chain a trader sees: one row per strike, call and put either side.

    Served as-of, because a strict reading of "the Chain at this moment" is nine
    strikes quoting both sides out of the ninety-four in the file - and on some minutes
    of this day, none at all. The last known quote at or before the moment gives 41.
    """
    sides: dict[float, dict[str, ChainQuote]] = {}
    strike_iv: dict[float, float] = {}
    for quote in snapshot(moment).to_dict("records"):
        strike_iv[float(quote["strike"])] = float(quote["strike_iv"])
        side = "call" if quote["option_type"] == "CE" else "put"
        sides.setdefault(float(quote["strike"]), {})[side] = ChainQuote(
            last=float(quote["last"]),
            open_interest=float(quote["OpenInterest"]),
            volume=float(quote["Volume"]),
            delta=float(quote["delta"]),
            age_minutes=int(quote["age_minutes"]),
        )

    rows = [
        ChainRow(
            strike=strike,
            iv=strike_iv.get(strike),
            call=sides[strike].get("call"),
            put=sides[strike].get("put"),
        )
        for strike in sorted(sides)
    ]
    fit = forward_at(moment)
    return ChainResponse(
        moment=str(pd.Timestamp(moment)),
        spot=spot_at(moment),
        expiry=expiry_label(),
        forward=fit.forward,
        discount=fit.discount,
        forward_method=fit.method,
        rows=rows,
    )

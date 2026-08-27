"""The HTTP surface.

Two endpoints. One returns the Chain at a moment; the other is **deliberately fat**
(#23) and returns everything about a
Strategy in a single response. Splitting it would mean several round trips carrying the
same Legs and recomputing the same curve, and the trader would watch the numbers arrive
after the chart they belong to.

**The server computes; the client never prices.**
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from payoff import catalog, chain, presets, strategy
from payoff.models import (
    AnalysisRequest,
    AnalysisResponse,
    ChainResponse,
    PresetResponse,
    SessionResponse,
)

app = FastAPI(title="convex-hedge payoff engine")


@app.exception_handler(presets.UnknownPreset)
def _unknown_preset(request: Request, error: presets.UnknownPreset) -> JSONResponse:
    """A name the picker does not offer. The status is here because a 500 would say the
    server broke and it did not; **#31 owns what the body looks like.**"""
    return JSONResponse(status_code=404, content={"detail": str(error)})


@app.exception_handler(catalog.NotStored)
def _not_stored(request: Request, error: catalog.NotStored) -> JSONResponse:
    """A date or an Expiry the build never wrote.

    404 rather than 500 for the same reason as above - the request is well-formed and the
    thing it names is simply not there - and the message is the whole improvement. This
    used to surface as `0 -- is not quoted at or before this moment`, because a date that
    was never built filters the store to nothing and the as-of slice was the first thing
    to notice. True, and about the wrong subject. **#31 owns the body's shape.**
    """
    return JSONResponse(status_code=404, content={"detail": str(error)})


@app.exception_handler(catalog.UnreadableExpiry)
def _unreadable_expiry(request: Request, error: catalog.UnreadableExpiry) -> JSONResponse:
    """Text that is not an Expiry label. 422: nothing was looked up, so nothing is missing."""
    return JSONResponse(status_code=422, content={"detail": str(error)})


@app.post("/analyse", response_model=AnalysisResponse)
def analyse(request: AnalysisRequest) -> AnalysisResponse:
    """Everything about one Strategy, as-of one moment, in one response."""
    legs = chain.resolve_legs(request.legs, request.moment)
    spot = chain.spot_at(request.moment)
    fit = chain.forward_at(request.moment)

    rows = strategy.leg_greeks(legs, fit.forward, fit.discount, fit.T)

    return AnalysisResponse(
        moment=request.moment,
        spot=spot,
        forward=fit.forward,
        discount=fit.discount,
        curve=strategy.curve(legs, spot),
        metrics=strategy.metrics(legs),
        table=strategy.payoff_table(legs, spot),
        greeks=rows,
        total_greeks=strategy.total_greeks(rows),
    )


@app.get("/session", response_model=SessionResponse)
def read_session(date: str | None = None, expiry: str | None = None) -> SessionResponse:
    """One day and one Expiry: which minutes exist, what else exists, what the picker offers.

    Asked whenever either dropdown moves. Everything else takes a `moment`, and this is
    the only way to learn which moments there are - so it is served from the data rather
    than from a clock, and a client that renders 376 stops is rendering 376 minutes that
    quoted. `dates` and `expiries` are the same argument one level up (#68): the two
    dropdowns are populated from here and never from a file, because a generated list is
    free to describe a day the engine would not serve.

    **The pair is resolved, not merely validated.** A trader changes the date and the
    Expiry in the URL is one interaction behind; `catalog.resolve` returns a pair the
    store actually holds, and `date` and `expiry` in the response say which - so what
    comes back is never an empty Chain and never a session describing a day `/chain`
    would refuse. `/chain` itself is strict, because it is asked for one specific thing.
    """
    on, series = catalog.resolve(date, expiry, default=chain.ANCHOR_DATE)
    stamps = chain.moments(on, series)
    low, high = chain.strike_bounds(on, series)

    return SessionResponse(
        date=on.isoformat(),
        dates=[day.isoformat() for day in catalog.dates()],
        moments=stamps,
        moment_count=len(stamps),
        first_moment=stamps[0],
        last_moment=stamps[-1],
        expiry=chain.expiry_label(on, series),
        expiries=[catalog.label(one) for one in catalog.expiries(on)],
        strike_min=low,
        strike_max=high,
        presets=list(presets.PRESETS),
    )


@app.get("/chain", response_model=ChainResponse)
def read_chain(
    moment: str, date: str | None = None, expiry: str | None = None
) -> ChainResponse:
    """The Chain as-of a moment: one row per strike, call and put either side.

    `date` is the trading date, which is what the store is keyed by and what a link
    carries now that a control picks one (#68). Omitted, it is taken off the moment: the
    session runs 03:45 to 10:00 UTC, so it never crosses a midnight and the two cannot
    disagree. Naming it is what makes the twenty-three days #67 built reachable without a
    client having to know that.

    `expiry` is the other partition key, spelled as the response spells it - `10FEB26`.
    Omitted, the Chain covers every series that traded that day, which is what it meant
    before there was a second dropdown to name one. Named, it covers exactly one; the day
    a second series exists, the difference is a Chain against two interleaved, and
    nothing on screen would say which was being read.

    **Strict, unlike `/session`.** A pair the store does not hold is a 404 naming what it
    does hold, not a quiet substitution: a Chain that is not the one that was asked for
    is indistinguishable from one that is.
    """
    return chain.as_of_view(moment, date, expiry)


@app.get("/presets", response_model=PresetResponse)
def list_presets() -> PresetResponse:
    """The short list the picker offers."""
    return PresetResponse(presets=list(presets.PRESETS))


@app.get("/presets/{name}", response_model=PresetResponse)
def build_preset(
    name: str,
    moment: str,
    strike: float | None = None,
    width: float = presets.DEFAULT_WIDTH,
    direction: int = 1,
) -> PresetResponse:
    """The Legs a Preset builds, as a trader would have picked them by hand.

    Returned as requests rather than analysed here, so that choosing a Preset and
    picking its Legs off the Chain are the same operation and not two paths that agree.
    """
    centre = chain.at_the_money(moment) if strike is None else strike
    return PresetResponse(
        presets=list(presets.PRESETS),
        legs=presets.build(name, centre, width=width, direction=direction),
    )

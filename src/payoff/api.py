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

from payoff import chain, presets, strategy
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
def read_session() -> SessionResponse:
    """The day itself: which minutes exist, what expires, and what the picker offers.

    Asked once, at boot. Everything else takes a `moment`, and this is the only way to
    learn which moments there are - so it is served from the data rather than from a
    clock, and a client that renders 376 stops is rendering 376 minutes that quoted.
    """
    stamps = chain.moments()
    low, high = chain.strike_bounds()

    return SessionResponse(
        moments=stamps,
        moment_count=len(stamps),
        first_moment=stamps[0],
        last_moment=stamps[-1],
        expiry=chain.expiry_label(),
        strike_min=low,
        strike_max=high,
        presets=list(presets.PRESETS),
    )


@app.get("/chain", response_model=ChainResponse)
def read_chain(moment: str) -> ChainResponse:
    """The Chain as-of a moment: one row per strike, call and put either side."""
    return chain.as_of_view(moment)


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

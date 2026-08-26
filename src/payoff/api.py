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
from payoff.models import AnalysisRequest, AnalysisResponse, ChainResponse, PresetResponse

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
        greeks=rows,
        total_greeks=strategy.total_greeks(rows),
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

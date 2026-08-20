"""The HTTP surface.

Two endpoints. One returns the Chain at a moment; the other is **deliberately fat**
(#23) and returns everything about a
Strategy in a single response. Splitting it would mean several round trips carrying the
same Legs and recomputing the same curve, and the trader would watch the numbers arrive
after the chart they belong to.

**The server computes; the client never prices.**
"""

from fastapi import FastAPI

from payoff import chain, strategy
from payoff.models import AnalysisRequest, AnalysisResponse, ChainResponse

app = FastAPI(title="convex-hedge payoff engine")


@app.post("/analyse", response_model=AnalysisResponse)
def analyse(request: AnalysisRequest) -> AnalysisResponse:
    """Everything about one Strategy, as-of one moment, in one response."""
    legs = chain.resolve_legs(request.legs, request.moment)
    spot = chain.spot_at(request.moment)

    return AnalysisResponse(
        moment=request.moment,
        spot=spot,
        curve=strategy.curve(legs, spot),
        metrics=strategy.metrics(legs),
    )


@app.get("/chain", response_model=ChainResponse)
def read_chain(moment: str) -> ChainResponse:
    """The Chain as-of a moment: one row per strike, call and put either side."""
    return chain.as_of_view(moment)

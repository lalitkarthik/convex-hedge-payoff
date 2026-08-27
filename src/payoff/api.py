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
    SummaryResponse,
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


@app.exception_handler(strategy.MixedExpiry)
def _mixed_expiry(request: Request, error: strategy.MixedExpiry) -> JSONResponse:
    """A Strategy whose Legs span more than one Expiry (#71).

    422 rather than 404 or 500: both series may be perfectly well stored, so nothing is
    missing and nothing broke. It is the *combination* that has no answer, which is what
    Unprocessable Entity means.

    Handled here rather than raised out of a pydantic validator so that the body is
    `{"detail": "..."}` like every other refusal on this surface, and so that the sentence
    a caller reads names the two series it sent. A validation envelope would say
    `body -> legs`, which is where the problem is and not what it is. **#31 owns the
    body's shape.**
    """
    return JSONResponse(status_code=422, content={"detail": str(error)})


@app.post("/analyse", response_model=AnalysisResponse)
def analyse(request: AnalysisRequest) -> AnalysisResponse:
    """Everything about one Strategy, as-of one moment, in one response.

    The Expiry comes off the **Legs** (#71) and the request no longer carries one. It is
    settled before anything is read, because it is what the reads are keyed by: the header
    figures below belong to one series at one minute, and a Strategy that named two would
    otherwise take them from whichever the store listed first.

    **The chart and the table are centred on the Forward, not on Spot** (#72). They were
    centred on Spot, which is a Spot-to-Forward conversion with the basis silently assumed
    to be zero - and it is +118.87 here, so the window sat two strike intervals to the
    left of the axis it was plotted against. `spot` is still published, because Spot is
    still observed and the screen still prints it; it is simply not what anything is
    plotted against any more.
    """
    series = strategy.sole_expiry(request.legs)
    legs = chain.resolve_legs(request.legs, request.moment)
    fit = chain.forward_at(request.moment, expiry=series)

    rows = strategy.leg_greeks(legs, fit.forward, fit.discount, fit.T)

    return AnalysisResponse(
        moment=request.moment,
        spot=chain.spot_at(request.moment, expiry=series),
        forward=fit.forward,
        discount=fit.discount,
        curve=strategy.curve(legs, fit.forward),
        metrics=strategy.metrics(legs),
        table=strategy.payoff_table(legs, fit.forward),
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


@app.get("/summary", response_model=SummaryResponse)
def read_summary(
    moment: str, date: str | None = None, expiry: str | None = None
) -> SummaryResponse:
    """The header at one minute: Spot, the Forward, the Discount Factor, the money (#69).

    **This is what moving the time control asks for.** The four figures belong to the
    minute rather than to a strike, and in the stored Chain they repeat across every one
    of that minute's ~196 rows; a drag across a session asked for them 375 times and
    opened the million-row artifact 375 times to do it. They live in a 375-row-a-day
    Summary now, and this reads one row of it. Nothing under this endpoint opens the Chain.

    Same keys and same rules as `/chain`: `date` off the moment when it is omitted,
    `expiry` spelled `10FEB26`, and **strict** - a pair the store does not hold is a 404
    naming what it does, never a quiet substitution.

    The numbers are the ones `/chain` publishes for the same minute, and by construction
    rather than by coincidence: the build reduces the Chain frame it is about to write.
    """
    return chain.summary_view(moment, date, expiry)


@app.get("/presets", response_model=PresetResponse)
def list_presets() -> PresetResponse:
    """The short list the picker offers."""
    return PresetResponse(presets=list(presets.PRESETS))


@app.get("/presets/{name}", response_model=PresetResponse)
def build_preset(
    name: str,
    moment: str,
    date: str | None = None,
    expiry: str | None = None,
    strike: float | None = None,
    width: float = presets.DEFAULT_WIDTH,
    direction: int = 1,
) -> PresetResponse:
    """The Legs a Preset builds, as a trader would have picked them by hand.

    Returned as requests rather than analysed here, so that choosing a Preset and
    picking its Legs off the Chain are the same operation and not two paths that agree.

    `date` and `expiry` name the series the Legs are built in, spelled as `/chain` spells
    them, because a Leg carries its own Expiry now (#71) and a Preset is a shape rather
    than a set of contracts. Omitted, they are the Chain's own answer for this minute -
    not a constant, which would hand a trader Legs in a series they are not looking at.
    """
    series = chain.expiry_at(moment, date, expiry)
    centre = chain.at_the_money(moment, date, expiry) if strike is None else strike
    return PresetResponse(
        presets=list(presets.PRESETS),
        legs=presets.build(name, centre, series, width=width, direction=direction),
    )

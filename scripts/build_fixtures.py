"""Capture the engine's answers as static JSON, for a frontend with no backend yet.

The skeleton in `web/` has no server to call. It could have been given invented numbers;
it is given **real ones**, because a fabricated payoff curve is the exact failure this
project exists to avoid - it renders, it looks right, and nothing downstream catches it.
Every figure here came out of `payoff.api`, through the same `TestClient` the test suite
uses, in-process and with no port.

    web/fixtures/
      session.json                     bounds, expiry, strike range, preset names
      chain/2026-01-27T06-30-00.json   one per minute - the /chain response verbatim
      presets/straddle.json            the Legs each Preset builds at the anchor

**One file per minute rather than one big file.** The time control has 376 stops and
each response is 20 KB; bundling all of them would be 7.7 MB the browser reads to show
one. Fetched on demand, this directory is a static mirror of the real API - wiring the
backend later changes a URL and nothing else.

Usage:  python scripts/build_fixtures.py
"""

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from payoff import chain, presets  # noqa: E402
from payoff.api import app  # noqa: E402
from payoff.pricing import black76_greeks  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "web" / "public" / "fixtures"
#: Under `public/` because Next serves that directory as-is: a fixture is reachable at
#: `/fixtures/chain/<moment>.json`, which is the same shape of URL the real API will
#: answer on. The swap is a base path, not a rewrite of how the client loads anything.

GREEKS = ("delta", "gamma", "vega", "theta", "rho")

SIGNIFICANT_DIGITS = 10
"""Written precision. Full float64 costs 40.5 KB a minute and 15.8 MB across the day;
ten significant digits costs 31.6 KB and 12.3 MB, and still agrees with the engine to
about 1e-10 - four orders tighter than the 1e-6 the golden test grades at, and further
still beyond anything a chart or a table can show. The engine keeps its full precision;
only this display copy is rounded."""


def rounded(value):
    """Ten significant digits, recursively.

    `%g` rather than `round()` because these numbers span 25,219.12 and 0.0004668 in one
    document, and a fixed number of decimal places flatters one at the other's expense.
    """
    if isinstance(value, float):
        return float(f"%.{SIGNIFICANT_DIGITS}g" % value)
    if isinstance(value, dict):
        return {key: rounded(item) for key, item in value.items()}
    if isinstance(value, list):
        return [rounded(item) for item in value]
    return value


def write(path: Path, payload) -> None:
    """Compact separators: a space after every comma, across 376 files, is 1.2 MB of air."""
    path.write_text(json.dumps(rounded(payload), separators=(",", ":")))


def file_stem(moment: str) -> str:
    """`2026-01-27 06:30:00` -> `2026-01-27T06-30-00`, which is safe in a URL path."""
    return moment.replace(" ", "T").replace(":", "-")


def contract_greeks(moment) -> dict:
    """All five Greeks per strike per side, per contract, at this minute.

    **This is a fixture artefact, not a proposed contract change.** The real
    `ChainQuote` publishes `delta` and nothing else; the other four reach a client
    through `POST /analyse`, which the skeleton has no server to call. Carrying them here
    is what lets its Greeks tab work for an arbitrary Strategy **without the client
    pricing anything** - aggregating `d x q x g` is multiplication, and a second
    implementation of Black-76 in TypeScript would be a second answer to the same
    question (ADR-0001).

    Priced exactly as `chain.snapshot` prices its delta: at this minute's forward,
    discount and T, and at the strike's one shared volatility.
    """
    quotes = chain.snapshot(moment)
    fit = chain.forward_at(moment)

    out: dict[str, dict[str, float]] = {}
    for call in (True, False):
        side = (quotes.option_type == "CE").to_numpy() == call
        if not side.any():
            continue
        strikes = quotes.strike.to_numpy(float)[side]
        greeks = black76_greeks(
            fit.forward,
            strikes,
            fit.T,
            quotes.strike_iv.to_numpy(float)[side],
            fit.discount,
            is_call=call,
        )
        for index, strike in enumerate(strikes):
            key = f"{strike:.0f}{'CE' if call else 'PE'}"
            out[key] = {name: float(np.asarray(greeks[name])[index]) for name in GREEKS}
    return out


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "chain").mkdir(parents=True)
    (OUT / "presets").mkdir(parents=True)

    client = TestClient(app)
    moments = [str(stamp) for stamp in chain.load_chain().ts.unique()]

    for moment in moments:
        response = client.get("/chain", params={"moment": moment})
        response.raise_for_status()
        body = response.json()
        body["contract_greeks"] = contract_greeks(moment)
        write(OUT / "chain" / f"{file_stem(moment)}.json", body)

    anchor = moments[len(moments) // 2]
    for name in presets.PRESETS:
        built = client.get(f"/presets/{name}", params={"moment": anchor})
        built.raise_for_status()
        write(OUT / "presets" / f"{name}.json", built.json())

    strikes = chain.load_chain().strike
    session = {
        "first_moment": moments[0],
        "last_moment": moments[-1],
        "moments": [file_stem(moment) for moment in moments],
        "moment_count": len(moments),
        "expiry": chain.expiry_label(),
        "strike_min": float(strikes.min()),
        "strike_max": float(strikes.max()),
        "presets": list(presets.PRESETS),
    }
    (OUT / "session.json").write_text(json.dumps(session, indent=2))

    written = sum(path.stat().st_size for path in OUT.rglob("*.json"))
    print(f"{len(moments)} minutes, {len(presets.PRESETS)} presets -> {OUT}")
    print(f"{written / 1e6:.1f} MB, expiry {session['expiry']}, "
          f"strikes {session['strike_min']:,.0f}-{session['strike_max']:,.0f}")


if __name__ == "__main__":
    main()

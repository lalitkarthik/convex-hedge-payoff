"use client";

import { useCallback, useEffect, useState } from "react";

import GreeksTable from "./GreeksTable";
import Header from "./Header";
import LegEditor from "./LegEditor";
import MetricsPanel from "./MetricsPanel";
import PayoffChart from "./PayoffChart";
import PayoffTable from "./PayoffTable";

import { ApiError, postAnalysis } from "@/lib/api";
import { answered, asking, edit, failed, shouldAsk, start } from "@/lib/analysing";
import { istClock } from "@/lib/format";
import { strategyHref, type View } from "@/lib/strategy-url";
import type {
  AnalysisResponse,
  ChainResponse,
  LegRequest,
  SessionResponse,
  SummaryResponse,
} from "@/lib/types";

/**
 * The analysis, rendered — and, since the Strategy became editable here, re-asked.
 *
 * **Nothing on this screen computes anything.** Every figure arrived in a `POST /analyse`:
 * the curve, the four metrics, the per-Leg Greeks, the strategy total and the payoff
 * table. What changed is who sends that request. The first one is the server component's;
 * every one after it is this component's, straight from the browser through the
 * same-origin `/api` rewrite. The engine is still the only thing that prices.
 *
 * ## Why the page stopped re-rendering
 *
 * Editing used to mean `router.replace`, which re-runs `app/analyse/page.tsx` - four
 * backend calls and the whole tree replaced, dimmed by `.main.pending` on the way. That is
 * fine for a control you nudge and unusable for one you drag, which is what the strike
 * slider is.
 *
 * So the URL is written with `window.history.replaceState` instead. It updates the address
 * bar without waking the router, so the link stays copyable and still reproduces this
 * screen in a cold tab - #32's whole point - while no longer being the transport for every
 * tick of a gesture. `router.replace` never pushed history entries either, so back and
 * forward behave exactly as they did.
 *
 * The state that results is `lib/analysing.ts`, and it is a separate module because the
 * hard part is invisible: sixty questions a second come back in whatever order the network
 * likes, and an answer allowed to arrive late settles the screen on a strike the thumb has
 * already left. That rule is asserted there without a browser; this file supplies the
 * clock, the timer and the `fetch`, and decides nothing.
 *
 * A fresh URL - a pasted link, or the back button - remounts this component, because
 * `page.tsx` keys it on the encoded Legs. So the server's answer wins whenever the server
 * is the one that spoke last, and no reconciliation is needed between the two.
 *
 * The Strategy itself is edited in `LegEditor`, which is where the Chain fetched by this
 * page is actually spent: a ladder per Leg to drag along, and a price to re-read whenever
 * a Leg lands somewhere new.
 */

type Tab = "pnl" | "greeks" | "table";

export default function AnalyseScreen({
  session,
  summary,
  analysis,
  chain,
  legs,
  view,
}: {
  session: SessionResponse;
  summary: SummaryResponse;
  analysis: AnalysisResponse;
  chain: ChainResponse;
  legs: LegRequest[];
  view: View;
}) {
  const [tab, setTab] = useState<Tab>("pnl");

  // The server's render is question zero, already answered. Everything after it is ours.
  const [state, setState] = useState(() => start(legs, analysis));

  const apply = useCallback(
    (next: LegRequest[]) => {
      setState((current) => edit(current, next));
      // Synchronous with the gesture rather than in an effect: the address bar is the
      // thing a trader copies, and it should never be a frame behind what is on screen.
      window.history.replaceState(null, "", strategyHref("/analyse", view, next));
    },
    [view],
  );

  /*
   * Ask, whenever there is something to ask and nothing already in flight.
   *
   * There is no timer here and that is the point. This was a 120ms throttle, which held a
   * drag to eight updates a second no matter how fast the engine answered - and it
   * answers in about ten milliseconds. The curve moved in visible steps because of a
   * constant, not because of the engine.
   *
   * The effect re-runs on every settle, so the next question goes out the instant the
   * last answer lands. Twenty ticks of a drag arriving during one request produce exactly
   * one more request, for wherever the thumb actually ended up.
   */
  useEffect(() => {
    if (!shouldAsk(state)) return;

    const seq = state.issued;
    const legs = state.legs;
    setState((current) => asking(current, seq));

    postAnalysis({ moment: view.moment, legs })
      .then((next) => setState((current) => answered(current, seq, next)))
      .catch((error) =>
        setState((current) =>
          failed(
            current,
            seq,
            error instanceof ApiError && error.detail ? error.detail : String(error),
          ),
        ),
      );
  }, [state, view.moment]);

  const current = state.analysis;

  return (
    <div className="shell">
      <Header summary={summary}>
        <a className="back" href={strategyHref("/", view, state.legs)}>
          ← Chain
        </a>
        {/* Which day and which series, as text rather than as the Chain's two dropdowns:
            an analysis is of one Strategy at one minute, and changing either underneath
            it would be changing the question rather than the view. The way to another
            day is back to the Chain, which is the link immediately to the left. */}
        <span className="chip">{view.date}</span>
        <span className="chip">{summary.expiry}</span>
        <span className="chip">as of {istClock(view.moment)} IST</span>
        <span className="chip">{session.moment_count} minutes in session</span>
      </Header>

      <div className="body analyse-body">
        <main className="main analyse-main">
          {state.legs.length === 0 ? (
            <p className="empty">
              No Legs in this link. Go back to the Chain and pick some — the analysis is of a
              Strategy, and an empty Strategy is a flat line at zero.
            </p>
          ) : (
            <>
              {/* The Forward, not Spot: the axis is in Forward, and a reference line
                  has to stand on the axis it is drawn against (#72). */}
              <PayoffChart
                curve={current.curve}
                forward={current.forward}
                breakevens={current.metrics.breakevens}
              />
              <div className="tabs" role="tablist">
                <button role="tab" aria-selected={tab === "pnl"} onClick={() => setTab("pnl")}>
                  P&amp;L
                </button>
                <button role="tab" aria-selected={tab === "greeks"} onClick={() => setTab("greeks")}>
                  Greeks
                </button>
                <button role="tab" aria-selected={tab === "table"} onClick={() => setTab("table")}>
                  Payoff Table
                </button>
              </div>

              {/*
                A refusal replaces the numbers and leaves the curve alone. The engine has
                declined to answer for the Strategy as it now stands, so publishing metrics
                beside that message would be publishing the previous position's - but the
                curve on screen is still a real answer about a real Strategy, and blanking
                it would cost more than it says.
              */}
              {state.problem ? (
                <p className="refusal" role="status">
                  {state.problem}
                </p>
              ) : (
                <>
                  {tab === "pnl" && <MetricsPanel metrics={current.metrics} />}

                  {tab === "greeks" && (
                    <>
                      <GreeksTable
                        legs={state.legs}
                        rows={current.greeks}
                        total={current.total_greeks}
                      />
                      <p className="note">
                        Per contract, no Lot Size. Δ and Γ are undiscounted, so Δ is bounded by 1
                        and a call&apos;s Δ less its put&apos;s is exactly 1. Θ is one trading
                        session.
                      </p>
                    </>
                  )}

                  {tab === "table" && (
                    <PayoffTable table={current.table} forward={current.forward} />
                  )}
                </>
              )}
            </>
          )}
        </main>

        <aside className="panel">
          <h2>
            Strategy — {state.legs.length} {state.legs.length === 1 ? "Leg" : "Legs"}
          </h2>
          <LegEditor legs={state.legs} chain={chain} onChange={apply} />
          {/* Spot is still here, and deliberately (#72). It stopped being the axis; it
              did not stop being observed, and it is the one figure on this line that is
              measured rather than fitted. */}
          <p className="note">
            Forward {current.forward.toFixed(2)} · discount {current.discount.toFixed(6)} · spot{" "}
            {current.spot.toFixed(2)}. The chart and the table are drawn in Forward. Every figure
            on this page came from one request, so none of them can be as-of a different minute.
          </p>
        </aside>
      </div>
    </div>
  );
}

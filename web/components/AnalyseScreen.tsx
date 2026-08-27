"use client";

import { useState } from "react";

import GreeksTable from "./GreeksTable";
import Header from "./Header";
import LegsStrip from "./LegsStrip";
import MetricsPanel from "./MetricsPanel";
import PayoffChart from "./PayoffChart";
import PayoffTable from "./PayoffTable";

import { istClock } from "@/lib/format";
import { strategyHref, type View } from "@/lib/strategy-url";
import type { AnalysisResponse, ChainResponse, LegRequest, SessionResponse } from "@/lib/types";

/**
 * The analysis, rendered. **Nothing here computes anything.**
 *
 * Every figure on this screen arrived in one `POST /analyse`: the curve, the four
 * metrics, the per-Leg Greeks, the strategy total and the payoff table. The only client
 * logic left is which tab is open — ephemeral interface state, which #32 explicitly
 * keeps *out* of the URL, because nobody wants a shared link that forces them onto the
 * sender's open tab.
 *
 * The three tabs are always present. A disabled tab advertises an absence; these are all
 * derived from the same response, so switching costs no request.
 */

type Tab = "pnl" | "greeks" | "table";

export default function AnalyseScreen({
  session,
  chain,
  analysis,
  legs,
  view,
}: {
  session: SessionResponse;
  chain: ChainResponse;
  analysis: AnalysisResponse;
  legs: LegRequest[];
  view: View;
}) {
  const [tab, setTab] = useState<Tab>("pnl");

  return (
    <div className="shell">
      <Header chain={chain}>
        <a className="back" href={strategyHref("/", view, legs)}>
          ← Chain
        </a>
        {/* Which day and which series, as text rather than as the Chain's two dropdowns:
            an analysis is of one Strategy at one minute, and changing either underneath
            it would be changing the question rather than the view. The way to another
            day is back to the Chain, which is the link immediately to the left. */}
        <span className="chip">{view.date}</span>
        <span className="chip">{chain.expiry}</span>
        <span className="chip">as of {istClock(view.moment)} IST</span>
        <span className="chip">{session.moment_count} minutes in session</span>
      </Header>

      <div className="body analyse-body">
        <main className="main analyse-main">
          {legs.length === 0 ? (
            <p className="empty">
              No Legs in this link. Go back to the Chain and pick some — the analysis is of a
              Strategy, and an empty Strategy is a flat line at zero.
            </p>
          ) : (
            <>
              <PayoffChart
                curve={analysis.curve}
                spot={analysis.spot}
                breakevens={analysis.metrics.breakevens}
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

              {tab === "pnl" && <MetricsPanel metrics={analysis.metrics} />}

              {tab === "greeks" && (
                <>
                  <GreeksTable legs={legs} rows={analysis.greeks} total={analysis.total_greeks} />
                  <p className="note">
                    Per contract, no Lot Size. Δ and Γ are undiscounted, so Δ is bounded by 1 and
                    a call's Δ less its put's is exactly 1. Θ is one trading session.
                  </p>
                </>
              )}

              {tab === "table" && <PayoffTable table={analysis.table} spot={analysis.spot} />}
            </>
          )}
        </main>

        <aside className="panel">
          <h2>
            Strategy — {legs.length} {legs.length === 1 ? "Leg" : "Legs"}
          </h2>
          {/*
            Read-only here. Editing a Leg is the Chain's job, where the quote it is being
            priced against is on screen beside it.
          */}
          <LegsStrip legs={legs} readOnly />
          <p className="note">
            Forward {analysis.forward.toFixed(2)} · discount {analysis.discount.toFixed(6)} ·
            spot {analysis.spot.toFixed(2)}. Every figure on this page came from one
            request, so none of them can be as-of a different minute.
          </p>
        </aside>
      </div>
    </div>
  );
}

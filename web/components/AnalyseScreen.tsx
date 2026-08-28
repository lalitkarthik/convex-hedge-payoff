"use client";

import { useCallback, useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import GreeksTable from "./GreeksTable";
import Header from "./Header";
import LegsStrip from "./LegsStrip";
import MetricsPanel from "./MetricsPanel";
import PayoffChart from "./PayoffChart";
import PayoffTable from "./PayoffTable";
import StrikeSlider from "./StrikeSlider";

import { istClock } from "@/lib/format";
import { strategyHref, type View } from "@/lib/strategy-url";
import { legalStrikes, withStrike } from "@/lib/strikes";
import type {
  AnalysisResponse,
  ChainResponse,
  LegRequest,
  SessionResponse,
  SummaryResponse,
} from "@/lib/types";

/**
 * The analysis, rendered. **Nothing here computes anything.**
 *
 * Every figure on this screen arrived in one `POST /analyse`: the curve, the four
 * metrics, the per-Leg Greeks, the strategy total and the payoff table.
 *
 * Two pieces of client state, and both are ephemeral interface state which #32 keeps
 * *out* of the URL: which tab is open, and which Leg the strike slider points at.
 * Nobody wants a shared link that forces them onto the sender's open tab, and which row
 * is highlighted is not part of the Strategy.
 *
 * **Moving a strike still computes nothing here.** It rewrites the address bar and lets
 * the server component render again, exactly as the Chain page does - so the answer on
 * screen is always one the engine gave, never one the client interpolated between two.
 *
 * The three tabs are always present. A disabled tab advertises an absence; these are all
 * derived from the same response, so switching costs no request.
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

  // Clamped rather than trusted: the Strategy can lose a Leg between renders, and an
  // index left pointing past the end would read `undefined.strike`.
  const [picked, setPicked] = useState(0);
  const selected = Math.min(picked, Math.max(0, legs.length - 1));
  const leg = legs[selected];

  const router = useRouter();
  const [pending, startTransition] = useTransition();

  // The Chain page's pattern, verbatim except for the path. `replace` rather than
  // `push` so dragging a slider does not fill the back button with every strike it
  // passed over, and `scroll: false` so the page does not jump on each commit.
  const go = useCallback(
    (next: LegRequest[]) => {
      startTransition(() =>
        router.replace(strategyHref("/analyse", view, next), { scroll: false }),
      );
    },
    [router, view],
  );

  return (
    <div className="shell">
      <Header summary={summary}>
        <a className="back" href={strategyHref("/", view, legs)}>
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
        <main className={`main analyse-main ${pending ? "pending" : ""}`}>
          {legs.length === 0 ? (
            <p className="empty">
              No Legs in this link. Go back to the Chain and pick some — the analysis is of a
              Strategy, and an empty Strategy is a flat line at zero.
            </p>
          ) : (
            <>
              {/* The Forward, not Spot: the axis is in Forward, and a reference line
                  has to stand on the axis it is drawn against (#72). */}
              <PayoffChart
                curve={analysis.curve}
                forward={analysis.forward}
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

              {tab === "table" && (
                <PayoffTable table={analysis.table} forward={analysis.forward} />
              )}
            </>
          )}
        </main>

        <aside className="panel">
          <h2>
            Strategy — {legs.length} {legs.length === 1 ? "Leg" : "Legs"}
          </h2>
          {/*
            Direction, Quantity and Entry Premium are still the Chain's job, where the
            quote a Leg is priced against is on screen beside it. The strike is editable
            here because the Chain now *is* on screen - the slider offers only what this
            minute quotes, so this is not editing blind.
          */}
          <LegsStrip legs={legs} readOnly selected={selected} onSelect={setPicked} />

          {leg && (
            <>
              <h2>Strike</h2>
              <StrikeSlider
                strikes={legalStrikes(chain.rows, leg.option_type)}
                strike={leg.strike}
                optionType={leg.option_type}
                disabled={pending}
                onCommit={(strike) => go(withStrike(legs, selected, strike))}
              />
              {legs.length > 1 && (
                <p className="note">
                  Moving the {legs.length === 2 ? "other" : "another"} Leg? Pick its row above.
                </p>
              )}
            </>
          )}
          {/* Spot is still here, and deliberately (#72). It stopped being the axis; it
              did not stop being observed, and it is the one figure on this line that is
              measured rather than fitted. */}
          <p className="note">
            Forward {analysis.forward.toFixed(2)} · discount {analysis.discount.toFixed(6)} ·
            spot {analysis.spot.toFixed(2)}. The chart and the table are drawn in Forward.
            Every figure on this page came from one request, so none of them can be as-of a
            different minute.
          </p>
        </aside>
      </div>
    </div>
  );
}

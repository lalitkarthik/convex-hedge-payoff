"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import ChainTable from "./ChainTable";
import GreeksTable from "./GreeksTable";
import Header from "./Header";
import LegsStrip from "./LegsStrip";
import MetricsPanel from "./MetricsPanel";
import PayoffChart from "./PayoffChart";
import PayoffTable from "./PayoffTable";
import PresetPicker from "./PresetPicker";
import TimeControl from "./TimeControl";

import { loadChain, loadPreset, loadSession } from "@/lib/fixtures";
import {
  curve,
  legGreeks,
  metrics as computeMetrics,
  payoffTable,
  totalGreeks,
} from "@/lib/skeleton-maths";
import type { ChainResponse, Direction, Leg, OptionType, Session } from "@/lib/types";

/**
 * The shell that holds the state.
 *
 * **No store.** Selected Legs and the current moment live here in `useState`; ephemeral
 * interface state (which tab is open) lives beside them. Zustand for four pieces of
 * state is machinery this project does not need, and #17 said so.
 *
 * **Every tab switch costs nothing.** The metrics, the Greeks and the payoff table are
 * all derived from the Legs already in hand, which is the same property the real backend
 * gets by returning them together from one fat `POST /analyse`.
 *
 * The at-the-money strike is chosen **nearest the Forward**, not nearest spot — the
 * basis reaches +118.87, more than two strike intervals, so the two disagree and the
 * money is a fact about the options rather than about the index.
 */

type Tab = "pnl" | "greeks" | "table";

function nearestQuoted(chain: ChainResponse, target: number): number {
  return chain.rows.reduce(
    (best, row) => (Math.abs(row.strike - target) < Math.abs(best - target) ? row.strike : best),
    chain.rows[0]?.strike ?? 0,
  );
}

export default function Terminal() {
  const [session, setSession] = useState<Session | null>(null);
  const [index, setIndex] = useState(0);
  const [chain, setChain] = useState<ChainResponse | null>(null);
  const [legs, setLegs] = useState<Leg[]>([]);
  const [tab, setTab] = useState<Tab>("pnl");

  useEffect(() => {
    loadSession().then((loaded) => {
      setSession(loaded);
      // Open on the anchor minute - 12:00 IST, where every published figure was measured.
      setIndex(Math.floor(loaded.moments.length / 2));
    });
  }, []);

  useEffect(() => {
    if (!session) return;
    let live = true;
    loadChain(session.moments[index]).then((loaded) => {
      if (live) setChain(loaded);
    });
    return () => {
      live = false;
    };
  }, [session, index]);

  const atTheMoney = useMemo(
    () => (chain ? nearestQuoted(chain, chain.forward) : 0),
    [chain],
  );

  const addLeg = useCallback(
    (strike: number, optionType: OptionType, direction: Direction) => {
      if (!chain) return;
      const row = chain.rows.find((candidate) => candidate.strike === strike);
      const quote = optionType === "CE" ? row?.call : row?.put;
      if (!quote) return;
      setLegs((current) => [
        ...current,
        {
          strike,
          optionType,
          direction,
          quantity: 1,
          // Entry Premium defaults to the Chain's last traded price, and is editable.
          entryPremium: quote.last,
          iv: row?.iv ?? null,
        },
      ]);
    },
    [chain],
  );

  const applyPreset = useCallback(
    async (name: string) => {
      if (!chain) return;
      const requests = await loadPreset(name);
      const built = requests.flatMap((request) => {
        const row = chain.rows.find((candidate) => candidate.strike === request.strike);
        const quote = request.option_type === "CE" ? row?.call : row?.put;
        // A Preset that opens with an unquoted Leg is worse than one that opens a strike
        // away, so a leg with no quote at this minute is dropped rather than faked.
        if (!quote) return [];
        return [
          {
            strike: request.strike,
            optionType: request.option_type,
            direction: request.direction,
            quantity: request.quantity ?? 1,
            entryPremium: quote.last,
            iv: row?.iv ?? null,
          } satisfies Leg,
        ];
      });
      setLegs(built);
    },
    [chain],
  );

  if (!session || !chain) {
    return <div className="shell" style={{ padding: 24, color: "var(--ink-faint)" }}>Loading…</div>;
  }

  const hasLegs = legs.length > 0;
  const metrics = hasLegs ? computeMetrics(legs) : null;
  const perLeg = hasLegs ? legGreeks(legs, chain.contract_greeks) : [];
  const total = hasLegs ? totalGreeks(perLeg) : null;

  return (
    <div className="shell">
      <Header chain={chain}>
        <TimeControl moments={session.moments} index={index} onChange={setIndex} />
      </Header>

      <div className="body">
        <main className="main">
          <ChainTable chain={chain} atTheMoney={atTheMoney} onPick={addLeg} />
        </main>

        <aside className="panel">
          <h2>
            Strategy — {legs.length} {legs.length === 1 ? "Leg" : "Legs"}
          </h2>

          <PresetPicker presets={session.presets} onPick={applyPreset} />

          <LegsStrip
            legs={legs}
            onChange={(at, leg) =>
              setLegs((current) => current.map((existing, i) => (i === at ? leg : existing)))
            }
            onRemove={(at) => setLegs((current) => current.filter((_, i) => i !== at))}
          />

          {/*
            Three tabs, always rendered - "a disabled tab advertises an absence". They
            are all derived from the same Legs, so switching costs no fetch.
          */}
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

          {!hasLegs && (
            <p className="note">
              Build a Strategy to see its P&amp;L at expiry, its exposures and its payoff table.
            </p>
          )}

          {hasLegs && tab === "pnl" && metrics && (
            <>
              <PayoffChart
                curve={curve(legs, chain.spot)}
                spot={chain.spot}
                breakevens={metrics.breakevens}
              />
              <MetricsPanel metrics={metrics} />
            </>
          )}

          {hasLegs && tab === "greeks" && (
            <>
              <GreeksTable legs={legs} rows={perLeg} total={total} />
              <p className="note">
                Per contract, no Lot Size. Δ and Γ carry the discount factor, so Δ is bounded by{" "}
                {chain.discount.toFixed(6)} rather than by 1. Θ is one trading session.
              </p>
            </>
          )}

          {hasLegs && tab === "table" && (
            <PayoffTable rows={payoffTable(legs, chain.spot)} spot={chain.spot} />
          )}
        </aside>
      </div>
    </div>
  );
}

"use client";

import { useRouter } from "next/navigation";
import { useCallback, useMemo, useTransition } from "react";

import ChainTable from "./ChainTable";
import Header from "./Header";
import LegsStrip from "./LegsStrip";
import PresetPicker from "./PresetPicker";
import TimeControl from "./TimeControl";

import { buildPreset } from "@/lib/api";
import { strategyHref } from "@/lib/strategy-url";
import type { ChainResponse, Direction, LegRequest, OptionType, SessionResponse } from "@/lib/types";

/**
 * The Chain screen: pick Legs, then go and look at them.
 *
 * **There is no store, and no local copy of the Strategy.** Every mutation writes the
 * URL and lets the server component re-render — so the address bar is not a reflection
 * of the state, it *is* the state (#32). The immediate payoff is that reload, back,
 * forward and paste all work without a line of code spent on them.
 *
 * `useTransition` is what keeps that from feeling slow: the previous chain stays on
 * screen, dimmed, while the next minute is fetched, instead of the table blanking.
 */
export default function ChainScreen({
  session,
  chain,
  legs,
}: {
  session: SessionResponse;
  chain: ChainResponse;
  legs: LegRequest[];
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  const index = useMemo(
    () => Math.max(0, session.moments.indexOf(chain.moment)),
    [session.moments, chain.moment],
  );

  const go = useCallback(
    (moment: string, next: LegRequest[]) => {
      startTransition(() => router.replace(strategyHref("/", moment, next), { scroll: false }));
    },
    [router],
  );

  const atTheMoney = useMemo(
    () =>
      chain.rows.reduce(
        (best, row) =>
          Math.abs(row.strike - chain.forward) < Math.abs(best - chain.forward) ? row.strike : best,
        chain.rows[0]?.strike ?? 0,
      ),
    [chain],
  );

  const addLeg = useCallback(
    (strike: number, optionType: OptionType, direction: Direction) => {
      const row = chain.rows.find((candidate) => candidate.strike === strike);
      const quote = optionType === "CE" ? row?.call : row?.put;
      if (!quote) return;
      // Entry Premium defaults to the Chain's last traded price and is editable — story
      // 18, "what if I had entered at X". It is carried in the URL so the link means the
      // same thing tomorrow, when the Chain no longer says 344.05.
      go(chain.moment, [
        ...legs,
        { strike, option_type: optionType, direction, quantity: 1, entry_premium: quote.last },
      ]);
    },
    [chain, legs, go],
  );

  const applyPreset = useCallback(
    async (name: string) => {
      const requested = await buildPreset(name, chain.moment);
      const built = requested.flatMap((leg) => {
        const row = chain.rows.find((candidate) => candidate.strike === leg.strike);
        const quote = leg.option_type === "CE" ? row?.call : row?.put;
        // A Preset that opens with an unquoted Leg is worse than one that opens a strike
        // away, so a Leg with no quote at this minute is dropped rather than faked.
        return quote ? [{ ...leg, entry_premium: quote.last }] : [];
      });
      go(chain.moment, built);
    },
    [chain, go],
  );

  return (
    <div className="shell">
      <Header chain={chain}>
        <TimeControl
          moments={session.moments}
          index={index}
          onChange={(next) => go(session.moments[next], legs)}
        />
      </Header>

      <div className="body">
        <main className={`main ${pending ? "pending" : ""}`}>
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
              go(
                chain.moment,
                legs.map((existing, i) => (i === at ? leg : existing)),
              )
            }
            onRemove={(at) => go(chain.moment, legs.filter((_, i) => i !== at))}
          />

          {legs.length === 0 ? (
            <p className="note">
              Click <strong>B</strong> or <strong>S</strong> on the Chain, or pick a Preset. The
              Strategy is kept in the address bar, so the link you copy is the position.
            </p>
          ) : (
            <a className="analyse" href={strategyHref("/analyse", chain.moment, legs)}>
              Analyse {legs.length} {legs.length === 1 ? "Leg" : "Legs"} →
            </a>
          )}
        </aside>
      </div>
    </div>
  );
}

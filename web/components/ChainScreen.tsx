"use client";

import { useRouter } from "next/navigation";
import { useCallback, useMemo, useTransition } from "react";

import ChainTable from "./ChainTable";
import Header from "./Header";
import LegsStrip from "./LegsStrip";
import PresetPicker from "./PresetPicker";
import TimeControl from "./TimeControl";
import ViewPicker from "./ViewPicker";

import { buildPreset } from "@/lib/api";
import { strategyHref, type View } from "@/lib/strategy-url";
import type {
  ChainResponse,
  Direction,
  LegRequest,
  OptionType,
  SessionResponse,
  SummaryResponse,
} from "@/lib/types";

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
  summary,
  chain,
  view,
  legs,
}: {
  session: SessionResponse;
  summary: SummaryResponse;
  chain: ChainResponse;
  view: View;
  legs: LegRequest[];
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  const index = useMemo(
    () => Math.max(0, session.moments.indexOf(chain.moment)),
    [session.moments, chain.moment],
  );

  const go = useCallback(
    (next: View, withLegs: LegRequest[]) => {
      startTransition(() => router.replace(strategyHref("/", next, withLegs), { scroll: false }));
    },
    [router],
  );

  /** Every navigation that keeps the day and the series, which is most of them. */
  const here = useCallback(
    (moment: string, next: LegRequest[]) => go({ ...view, moment }, next),
    [go, view],
  );

  /**
   * A different day, at the same clock time.
   *
   * The moment is rewritten onto the new date rather than carried across whole, so the
   * link never reads `date=2026-01-07&moment=2026-01-27T…` — two days in one address,
   * which reload resolves correctly and a person cannot. Only the date part is replaced;
   * the stamps are fixed-width ISO 8601, and re-formatting the engine's own strings is
   * how a spelling drifts.
   *
   * Whether that minute exists is not something this side can know — 7 January quoted
   * 150 of the session's 376 — so `pickMoment` settles it on the next render, against
   * the session for the day that was actually picked.
   *
   * The Expiry is carried rather than cleared: it is still what the trader chose, and
   * the engine resolves it to one the new date traded if that day never traded it. The
   * Legs are carried too — a Leg is a strike and a side in a series, and the series has
   * not changed, so "what would this have looked like on the 7th" is a question the link
   * can still ask.
   */
  const goDate = useCallback(
    (date: string) => go({ ...view, date, moment: date + view.moment.slice(10) }, legs),
    [go, view, legs],
  );

  /**
   * A different series, and the Legs do **not** come with it.
   *
   * A Leg names a strike and a side, and which contract that is depends on the Expiry.
   * Carrying 25,200 CE from one series into another would keep the label and silently
   * change the instrument, which is the failure mode #64 rejects a calendar Strategy
   * over rather than drawing something plausible.
   */
  const goExpiry = useCallback(
    (expiry: string) => go({ ...view, expiry }, []),
    [go, view],
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
      here(chain.moment, [
        ...legs,
        { strike, option_type: optionType, direction, quantity: 1, entry_premium: quote.last },
      ]);
    },
    [chain, legs, here],
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
      here(chain.moment, built);
    },
    [chain, here],
  );

  return (
    <div className="shell">
      <Header summary={summary}>
        <ViewPicker session={session} onDate={goDate} onExpiry={goExpiry} />
        <TimeControl
          moments={session.moments}
          index={index}
          onChange={(next) => here(session.moments[next], legs)}
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
              here(
                chain.moment,
                legs.map((existing, i) => (i === at ? leg : existing)),
              )
            }
            onRemove={(at) => here(chain.moment, legs.filter((_, i) => i !== at))}
          />

          {legs.length === 0 ? (
            <p className="note">
              Click <strong>B</strong> or <strong>S</strong> on the Chain, or pick a Preset. The
              Strategy is kept in the address bar, so the link you copy is the position.
            </p>
          ) : (
            <a className="analyse" href={strategyHref("/analyse", view, legs)}>
              Analyse {legs.length} {legs.length === 1 ? "Leg" : "Legs"} →
            </a>
          )}
        </aside>
      </div>
    </div>
  );
}

import type { AnalysisResponse, LegRequest } from "@/lib/types";

/**
 * The Analyse screen's state while it is being edited, as a pure reducer.
 *
 * Editing a Strategy used to mean writing the URL and letting the server component render
 * again - four backend calls and the whole tree replaced, with `.main.pending` dimming it
 * on the way. Fine for a control you nudge; unusable for one you drag. The page holds the
 * Strategy itself now and asks `/analyse` directly, which it can do because
 * `apiBase()` already routes a browser through the same-origin `/api` rewrite.
 *
 * **The client still prices nothing.** Every figure on screen is one the engine returned;
 * what changed is who asked and how often, not who computed. That is the rule
 * `skeleton-maths.ts` was deleted for and it is untouched here.
 *
 * All the difficulty is in one place. Sixty questions a second come back in whatever
 * order the network feels like, so this module is the arbiter of which answers are
 * allowed to reach the screen, and it is pure so that can be asserted without a browser.
 * The component supplies the clock, the timer and the `fetch`; it makes no decisions.
 */
export interface Analysing {
  /** The Strategy as edited. The URL is written from this, and it is what gets asked. */
  legs: LegRequest[];
  /** The last answer the engine gave. Never cleared - see `edit`. */
  analysis: AnalysisResponse;
  /** Which question is outstanding. Answers are matched against it and nothing else. */
  issued: number;
  /** The engine's refusal, if the newest question got one. */
  problem: string | null;
}

/** The server's render, as the starting position. */
export function start(legs: LegRequest[], analysis: AnalysisResponse): Analysing {
  return { legs, analysis, issued: 0, problem: null };
}

/**
 * A new Strategy, and a new question about it.
 *
 * **The last good answer is kept.** Blanking the chart for the length of a request would
 * make a drag unreadable, and it would be saying the wrong thing: a missing curve reads
 * as "this position has no answer", where the truth is "the answer is a moment behind".
 * The figures on screen are always ones the engine gave about a Strategy the trader had -
 * just possibly the one from a few milliseconds ago.
 */
export function edit(state: Analysing, legs: LegRequest[]): Analysing {
  return { ...state, legs, issued: state.issued + 1 };
}

/**
 * The engine's answer, applied only if it is still the answer to the current question.
 *
 * The identity comparison is the whole point. Ask about 25,200, ask about 25,600, then
 * have the first answer land second: without this the screen settles on the curve for a
 * strike the thumb has already left, and nothing ever corrects it - the answer that
 * would have has already arrived and been overwritten.
 */
export function answered(state: Analysing, seq: number, analysis: AnalysisResponse): Analysing {
  if (seq !== state.issued) return state;
  return { ...state, analysis, problem: null };
}

/**
 * A refusal, under the same rule.
 *
 * The stale guard matters more here than for a success: a slow 404 from a strike the drag
 * passed over would otherwise replace a perfectly good curve with an error about a
 * position the trader is not in.
 *
 * The last good `analysis` survives a failure. The refusal is said - #23's error contract
 * would rather fail plainly than draw something plausible - but the curve that was
 * already correct has done nothing wrong.
 */
export function failed(state: Analysing, seq: number, problem: string): Analysing {
  if (seq !== state.issued) return state;
  return { ...state, problem };
}

/**
 * When the next request may go out: now, or the end of the current window.
 *
 * Leading edge, so the first tick of a drag is not preceded by a wait. Deferred rather
 * than dropped inside the window, which is the half that is easy to get wrong: the
 * position a drag *ends* on almost always falls inside the window, and a throttle that
 * dropped it would leave the screen showing the second-to-last strike permanently.
 */
export function dueAt(now: number, lastSent: number, interval: number): number {
  return Math.max(now, lastSent + interval);
}

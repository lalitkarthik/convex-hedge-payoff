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
  /** The newest question. Bumped by every edit, whether or not it has been asked yet. */
  issued: number;
  /** The question currently in flight, or null. At most one, ever - see `shouldAsk`. */
  asked: number | null;
  /** The newest question that has come back, answered or refused. */
  settled: number;
  /** The engine's refusal, if the newest question got one. */
  problem: string | null;
}

/** The server's render, as the starting position. */
export function start(legs: LegRequest[], analysis: AnalysisResponse): Analysing {
  // Question zero arrived with the page, already answered. `settled` says so, which is
  // what stops the first render asking the server what it just told us.
  return { legs, analysis, issued: 0, asked: null, settled: 0, problem: null };
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
  if (seq !== state.asked) return state;
  return { ...state, analysis, problem: null, asked: null, settled: seq };
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
  if (seq !== state.asked) return state;
  // Settled, not merely cleared. A refusal that left the question outstanding would be
  // re-asked immediately and forever, as fast as the refusals came back.
  return { ...state, problem, asked: null, settled: seq };
}

/**
 * Whether there is a question to ask right now.
 *
 * **One in flight at a time, and no clock.** This replaced a 120ms throttle, which held a
 * drag to eight updates a second however fast the engine answered - and it answers in
 * about ten milliseconds through the rewrite, so the constant was capping a fast thing to
 * a guess made while the backend was not running.
 *
 * Asking again the moment the last answer lands has no constant in it. It runs at
 * whatever rate the engine sustains, slows down by itself if the engine slows down, and
 * cannot pile requests up - which is the thing the throttle was really for. Twenty ticks
 * of a drag landing during one request produce exactly one more request, for wherever the
 * thumb actually ended up, because only `issued` moved and it is read once.
 *
 * It also demotes out-of-order answers from a handled case to an impossible one: there is
 * never more than one outstanding. `answered` still checks, because a guarantee that
 * costs one comparison is worth keeping when the cost of losing it is a curve that
 * silently describes the wrong Strategy.
 */
export function shouldAsk(state: Analysing): boolean {
  return state.asked === null && state.issued !== state.settled;
}

/**
 * Mark a question as the one in flight.
 *
 * The sequence is passed in rather than read off `state.issued`, and that is not
 * ceremony. The caller has already captured which Legs it is about to send; if an edit
 * landed in between, reading `issued` here would record a question number the outgoing
 * request does not carry - so its answer would be discarded as stale, `asked` would never
 * clear, and `shouldAsk` would be false forever. A frozen chart with no error anywhere.
 */
export function asking(state: Analysing, seq: number): Analysing {
  return { ...state, asked: seq };
}

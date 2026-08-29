import { describe, expect, test } from "bun:test";

import { answered, asking, edit, failed, shouldAsk, start } from "./analysing";
import type { AnalysisResponse, LegRequest } from "./types";

/**
 * Dragging a slider asks the engine a question sixty times a second, and the answers do
 * not come back in the order they were asked.
 *
 * That is the whole of this file. Everything else about the live Analyse screen is
 * plumbing; **out-of-order responses are the one thing here that is genuinely hard**, and
 * they are hard in the way that does not show up in a demo - the drag looks right, and
 * then once in twenty gestures the curve settles on a strike the thumb has already left.
 * So the rule lives in a pure reducer where it can be asserted without a browser, and the
 * component is left holding nothing but a timer and a `fetch`.
 *
 * Two invariants, and the second is the one that is easy to lose:
 *
 *  - **Only the newest request may change the screen.** Any answer, or any failure, from
 *    a request that has since been superseded is discarded.
 *  - **The last good answer stays up.** The chart never blanks mid-drag and never blanks
 *    on an error, because a missing curve says "this position has no answer" and the
 *    truth is "the answer is a moment behind".
 */

const EXPIRY = "10FEB26";

const LEG: LegRequest[] = [
  { strike: 25200, option_type: "CE", expiry: EXPIRY, direction: -1, quantity: 1, entry_premium: 344.05 },
];
const MOVED: LegRequest[] = [{ ...LEG[0]!, strike: 25250, entry_premium: 317.75 }];

/** Distinguished by `spot` alone; nothing here reads any other field. */
const answer = (spot: number) => ({ spot }) as unknown as AnalysisResponse;

const FIRST = answer(1);
const SECOND = answer(2);

describe("edit", () => {
  test("swaps the Legs and asks a new question", () => {
    const after = edit(start(LEG, FIRST), MOVED);

    expect(after.legs).toEqual(MOVED);
    expect(after.issued).toBe(1);
  });

  test("keeps the last good answer on screen", () => {
    // The chart must not blank while the next one is in flight. A curve that vanishes
    // on every tick of a drag is unreadable; a curve 100ms behind is not wrong, only
    // recent.
    expect(edit(start(LEG, FIRST), MOVED).analysis).toBe(FIRST);
  });

  test("every edit is a new question, so two in a row are told apart", () => {
    expect(edit(edit(start(LEG, FIRST), MOVED), LEG).issued).toBe(2);
  });
});

describe("answered", () => {
  test("the newest request's answer is shown", () => {
    // `asking` is part of the lifecycle now: a question has to be in flight before an
    // answer to it means anything. That is what makes a reply nobody asked for a no-op.
    const asked = asking(edit(start(LEG, FIRST), MOVED), 1);
    expect(answered(asked, asked.asked!, SECOND).analysis).toBe(SECOND);
  });

  test("an answer to a superseded request is discarded", () => {
    // The bug this module exists for. Ask twice, answer the first: the state must not
    // move, or the screen shows the curve for a strike the thumb has already left and
    // nothing ever corrects it, because the second answer has already been and gone.
    const first = asking(edit(start(LEG, FIRST), MOVED), 1);
    const second = asking(edit(first, LEG), 2);

    expect(answered(second, first.asked!, SECOND)).toBe(second);
  });

  test("an answer clears a problem left by an earlier failure", () => {
    const asked = asking(edit(start(LEG, FIRST), MOVED), 1);
    const broken = failed(asked, asked.asked!, "no");
    const again = asking(edit(broken, LEG), 2);

    expect(answered(again, again.asked!, SECOND).problem).toBeNull();
  });
});

describe("failed", () => {
  test("the message is shown and the last good answer is kept", () => {
    // Both halves matter. A refusal has to be said - #23's error contract would rather
    // fail loudly than draw something plausible - and the curve that was already correct
    // has no reason to disappear along with it.
    const asked = asking(edit(start(LEG, FIRST), MOVED), 1);
    const broken = failed(asked, asked.asked!, "25201 CE is not quoted at this moment");

    expect(broken.problem).toBe("25201 CE is not quoted at this moment");
    expect(broken.analysis).toBe(FIRST);
  });

  test("a failure from a superseded request is discarded", () => {
    // A slow 404 for a strike the drag passed over must not replace a good answer with
    // an error, which would put a refusal on screen for a position the trader is not in.
    const first = asking(edit(start(LEG, FIRST), MOVED), 1);
    const second = asking(edit(first, LEG), 2);

    expect(failed(second, first.asked!, "too late")).toBe(second);
  });
});

describe("shouldAsk and asking", () => {
  /*
   * The pacing rule, and it is deliberately not a clock.
   *
   * This was a 120ms throttle, which meant a drag updated the curve eight times a second
   * however fast the engine answered - and the engine answers in about ten milliseconds
   * through the rewrite. The number was doing nothing but capping a fast thing to a
   * guess made when the backend was not running.
   *
   * So: **one question in flight at a time, and ask again the moment it lands if the
   * Strategy has moved on.** That has no constant in it. It runs at whatever speed the
   * engine can answer, degrades on its own if the engine is slow, and cannot pile up
   * requests - which is what the throttle was really protecting against.
   *
   * It also makes an out-of-order answer impossible rather than merely handled, since
   * there is never more than one outstanding.
   */

  test("a fresh Strategy is asked about immediately", () => {
    expect(shouldAsk(edit(start(LEG, FIRST), MOVED))).toBe(true);
  });

  test("the server's own render is not asked about again", () => {
    // Question zero arrived with the page. Asking it again would double every page load.
    expect(shouldAsk(start(LEG, FIRST))).toBe(false);
  });

  test("nothing is asked while a question is outstanding", () => {
    const state = edit(start(LEG, FIRST), MOVED);
    expect(shouldAsk(asking(state, state.issued))).toBe(false);
  });

  test("an edit landing mid-request still settles, rather than freezing", () => {
    // `asking` takes the sequence rather than reading `issued`, so a question asked about
    // one Strategy is still the question that gets answered even if the trader has moved
    // on. Recording the newer number here would strand `asked` set forever: the answer
    // would look stale, nothing would clear it, and the chart would freeze silently.
    const first = edit(start(LEG, FIRST), MOVED);
    const asked = asking(first, first.issued);
    const later = edit(asked, LEG);

    const settled = answered(later, first.issued, SECOND);
    expect(settled.asked).toBeNull();
    expect(shouldAsk(settled)).toBe(true);
  });

  test("edits during a request do not queue up - only the newest is asked", () => {
    // The drag case. Twenty ticks land while one request is in flight; when it returns,
    // exactly one more request goes out, for where the thumb actually is.
    let state = asking(edit(start(LEG, FIRST), MOVED), 1);
    for (let i = 0; i < 20; i++) state = edit(state, LEG);

    expect(shouldAsk(state)).toBe(false);

    state = answered(state, 1, SECOND);
    expect(shouldAsk(state)).toBe(true);
    expect(asking(state, state.issued).asked).toBe(state.issued);
  });

  test("a settled Strategy is left alone", () => {
    const asked = asking(edit(start(LEG, FIRST), MOVED), 1);
    expect(shouldAsk(answered(asked, asked.issued, SECOND))).toBe(false);
  });

  test("a refusal still settles the question, so the loop does not spin", () => {
    // Without this a Strategy the engine refuses would be re-asked forever, as fast as
    // the refusals came back.
    const asked = asking(edit(start(LEG, FIRST), MOVED), 1);
    expect(shouldAsk(failed(asked, asked.issued, "no"))).toBe(false);
  });
});

import { describe, expect, test } from "bun:test";

import { answered, dueAt, edit, failed, start } from "./analysing";
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
    const asked = edit(start(LEG, FIRST), MOVED);
    expect(answered(asked, asked.issued, SECOND).analysis).toBe(SECOND);
  });

  test("an answer to a superseded request is discarded", () => {
    // The bug this module exists for. Ask twice, answer the first: the state must not
    // move, or the screen shows the curve for a strike the thumb has already left and
    // nothing ever corrects it, because the second answer has already been and gone.
    const first = edit(start(LEG, FIRST), MOVED);
    const second = edit(first, LEG);

    expect(answered(second, first.issued, SECOND)).toBe(second);
  });

  test("an answer clears a problem left by an earlier failure", () => {
    const asked = edit(start(LEG, FIRST), MOVED);
    const broken = failed(asked, asked.issued, "no");
    const again = edit(broken, LEG);

    expect(answered(again, again.issued, SECOND).problem).toBeNull();
  });
});

describe("failed", () => {
  test("the message is shown and the last good answer is kept", () => {
    // Both halves matter. A refusal has to be said - #23's error contract would rather
    // fail loudly than draw something plausible - and the curve that was already correct
    // has no reason to disappear along with it.
    const asked = edit(start(LEG, FIRST), MOVED);
    const broken = failed(asked, asked.issued, "25201 CE is not quoted at this moment");

    expect(broken.problem).toBe("25201 CE is not quoted at this moment");
    expect(broken.analysis).toBe(FIRST);
  });

  test("a failure from a superseded request is discarded", () => {
    // A slow 404 for a strike the drag passed over must not replace a good answer with
    // an error, which would put a refusal on screen for a position the trader is not in.
    const first = edit(start(LEG, FIRST), MOVED);
    const second = edit(first, LEG);

    expect(failed(second, first.issued, "too late")).toBe(second);
  });
});

describe("dueAt", () => {
  const INTERVAL = 120;

  test("the first request goes immediately", () => {
    // Leading edge. A throttle that waited out its own window before the first request
    // would put a visible lag on the start of every drag.
    expect(dueAt(1000, -Infinity, INTERVAL)).toBe(1000);
  });

  test("a request outside the window goes immediately", () => {
    expect(dueAt(1200, 1000, INTERVAL)).toBe(1200);
  });

  test("a request inside the window is deferred, never dropped", () => {
    // Deferred rather than dropped is the point: the position the drag *ends* on is
    // usually asked for inside the window, and dropping it would leave the screen
    // showing the second-to-last strike for good.
    expect(dueAt(1050, 1000, INTERVAL)).toBe(1120);
  });

  test("the boundary counts as outside", () => {
    expect(dueAt(1120, 1000, INTERVAL)).toBe(1120);
  });
});

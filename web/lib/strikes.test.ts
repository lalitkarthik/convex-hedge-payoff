import { describe, expect, test } from "bun:test";

import { decodeLegs, encodeLegs } from "./legs-url";
import { addLeg, legalStrikes, moveLeg, nearestIndex, quoteAt } from "./strikes";
import type { ChainRow, LegRequest } from "./types";

/**
 * The ladder the strike slider runs along.
 *
 * One property carries this file: **every strike the slider can stop on is a strike the
 * engine can price.** The two conditions `resolve_legs` applies are that the
 * `(strike, option_type)` pair is in the minute's snapshot and that the strike carries
 * an implied volatility; these functions apply the same two, so the reachable set and
 * the priceable set are the same set. Get that wrong and dragging produces a 404 or a
 * 422 - which are now clean refusals rather than 500s, but are still a dead end for
 * something the trader was invited to do.
 *
 * The shape below is the anchor's in miniature: 50 of its 91 strikes quote one side
 * only, so a row that is present but blank on the side asked for is the common case.
 * Every quote carries a **different** last traded price, which is what makes repricing
 * observable - with one price everywhere, a Leg that kept the old strike's premium and
 * a Leg that was correctly repriced would be indistinguishable.
 */

const EXPIRY = "10FEB26";
const FORWARD = 25219.12;

const q = (last: number) => ({ last, open_interest: 0, volume: 0, age_minutes: 0, delta: 0.5 });

const ROWS: ChainRow[] = [
  { strike: 25000, iv: 0.12, call: q(410.5), put: q(210.25) },
  { strike: 25100, iv: 0.12, call: q(360.75), put: null }, //  call only
  { strike: 25200, iv: 0.12, call: q(344.05), put: q(326.7) },
  { strike: 25300, iv: 0.12, call: null, put: q(402.15) }, //  put only
  { strike: 25400, iv: null, call: q(1), put: q(1) }, //       both sides, no volatility
];

describe("legalStrikes", () => {
  test("a strike quoted on the side asked for is offered", () => {
    expect(legalStrikes(ROWS, "CE")).toEqual([25000, 25100, 25200]);
  });

  test("the two sides give different ladders", () => {
    // Which is why the ladder is rebuilt when the selected Leg changes, and why a
    // slider that indexed a single shared ladder would put a call on a put-only strike.
    expect(legalStrikes(ROWS, "PE")).toEqual([25000, 25200, 25300]);
  });

  test("a strike carrying no volatility is left out of both", () => {
    // 25400 is quoted on both sides and still cannot be priced. This is the second of
    // `resolve_legs`' two conditions, and the one that is easy to forget because the
    // strike looks entirely healthy on the Chain.
    expect(legalStrikes(ROWS, "CE")).not.toContain(25400);
    expect(legalStrikes(ROWS, "PE")).not.toContain(25400);
  });

  test("the ladder is ascending, whatever order the Chain arrived in", () => {
    const shuffled = [...ROWS].reverse();
    expect(legalStrikes(shuffled, "CE")).toEqual([25000, 25100, 25200]);
  });

  test("a Chain with nothing quoted yields an empty ladder rather than throwing", () => {
    // Early minutes are sparse, and the first minute of a date can quote nothing at
    // all. The slider has to render disabled, not crash the page.
    expect(legalStrikes([], "CE")).toEqual([]);
  });
});

describe("nearestIndex", () => {
  const LADDER = [25000, 25100, 25200, 25300];

  test("a strike on the ladder finds its own position", () => {
    expect(nearestIndex(LADDER, 25200)).toBe(2);
    expect(nearestIndex(LADDER, 25000)).toBe(0);
  });

  test("a strike that has fallen off the ladder lands on the nearest one", () => {
    // The realistic case, and the reason this cannot just be `indexOf`. A Leg is built
    // at a minute where its strike is quoted, the trader drags the *time* control, and
    // that strike has not printed yet. `indexOf` would return -1 and park the thumb at
    // the far left, which reads as "your Leg is the lowest strike" - a lie about the
    // position, told silently.
    expect(nearestIndex(LADDER, 25190)).toBe(2);
    expect(nearestIndex(LADDER, 25260)).toBe(3);
  });

  test("a strike beyond either end clamps rather than escaping the ladder", () => {
    expect(nearestIndex(LADDER, 1)).toBe(0);
    expect(nearestIndex(LADDER, 99999)).toBe(3);
  });

  test("an exact tie resolves low, and does so every time", () => {
    // 25150 is 50 from both 25100 and 25200. Either would be defensible; what would not
    // be is picking a different one on different renders, which would make the thumb
    // jitter between two positions while nothing changed.
    expect(nearestIndex(LADDER, 25150)).toBe(1);
    expect(nearestIndex(LADDER, 25150)).toBe(1);
  });

  test("an empty ladder is 0, not -1", () => {
    // Nothing is quoted, so the slider is disabled anyway - but it must not be handed
    // an index that would read past the end of the array.
    expect(nearestIndex([], 25200)).toBe(0);
  });
});

describe("quoteAt", () => {
  test("finds the quote on the side asked for", () => {
    expect(quoteAt(ROWS, 25200, "CE")?.last).toBe(344.05);
    expect(quoteAt(ROWS, 25200, "PE")?.last).toBe(326.7);
  });

  test("a side that is not quoted is null, never the other side's quote", () => {
    // 25,100 is a call-only strike. Falling back to the put here would price a Leg at a
    // contract nobody asked for, and the two prices differ by 150 points.
    expect(quoteAt(ROWS, 25100, "PE")).toBeNull();
  });

  test("a strike the Chain does not carry is null", () => {
    expect(quoteAt(ROWS, 99999, "CE")).toBeNull();
  });
});

describe("moveLeg", () => {
  const STRADDLE: LegRequest[] = [
    { strike: 25200, option_type: "CE", expiry: EXPIRY, direction: -1, quantity: 1, entry_premium: 344.05 },
    { strike: 25200, option_type: "PE", expiry: EXPIRY, direction: -1, quantity: 1, entry_premium: 326.7 },
  ];

  test("the moved Leg never keeps the old strike's premium", () => {
    // The assertion this whole feature turns on, and the one that survived a change of
    // mechanism. `entry_premium` is a bare float on the wire, so the server cannot tell
    // a premium left over from the old strike from a deliberate "what if I had entered
    // at X" - and a short 25,200 call dragged to 25,100 still claiming 344.05 publishes
    // a Breakeven that is wrong with nothing on screen contradicting it.
    const moved = moveLeg(STRADDLE, 0, { strike: 25100 }, ROWS)[0]!;

    expect(moved.strike).toBe(25100);
    expect(moved.entry_premium).not.toBe(344.05);
  });

  test("it is repriced from the Chain, not blanked", () => {
    // What changed. Leaving the field absent also satisfied the test above - absent
    // means "server, read the Chain's last" and the server would have found this very
    // number. But the client is now holding the Chain, so it can say the price instead
    // of asking for it, and the box on screen shows 360.75 rather than a placeholder.
    expect(moveLeg(STRADDLE, 0, { strike: 25100 }, ROWS)[0]!.entry_premium).toBe(360.75);
  });

  test("everything else about the moved Leg survives", () => {
    // Direction is separate from Quantity (CONTEXT.md): sold two is direction -1 and
    // quantity 2, never quantity -2. Losing either here would redraw the curve.
    const moved = moveLeg(STRADDLE, 0, { strike: 25100 }, ROWS)[0]!;

    expect(moved.option_type).toBe("CE");
    expect(moved.direction).toBe(-1);
    expect(moved.quantity).toBe(1);
    expect(moved.expiry).toBe(EXPIRY);
  });

  test("flipping to a side that quotes the same strike keeps the strike", () => {
    const flipped = moveLeg(STRADDLE, 0, { option_type: "PE" }, ROWS)[0]!;

    expect(flipped.strike).toBe(25200);
    expect(flipped.option_type).toBe("PE");
    expect(flipped.entry_premium).toBe(326.7);
  });

  test("flipping to a side that does not quote the strike snaps to one that does", () => {
    // The ladders are genuinely per-side - 50 of the anchor's 91 strikes quote one side
    // only - so a flip that kept the strike would land the Leg on a contract the engine
    // cannot price, which is the 404 the whole ladder design exists to make unreachable.
    const leg: LegRequest[] = [
      { strike: 25100, option_type: "CE", expiry: EXPIRY, direction: 1, quantity: 1, entry_premium: 360.75 },
    ];
    const flipped = moveLeg(leg, 0, { option_type: "PE" }, ROWS)[0]!;

    expect(legalStrikes(ROWS, "PE")).toContain(flipped.strike);
    expect(flipped.entry_premium).toBe(quoteAt(ROWS, flipped.strike, "PE")!.last);
    // 25,000 and 25,200 are both 100 away; `nearestIndex` resolves a tie low and does so
    // on every render, which is what stops the thumb jittering between two rungs.
    expect(flipped.strike).toBe(25000);
  });

  test("the other Legs are untouched, premium included", () => {
    // Only the Leg being moved is repriced. A sibling's Entry Premium may be a
    // deliberate override, and rewriting it would move a Breakeven the trader set.
    expect(moveLeg(STRADDLE, 0, { strike: 25100 }, ROWS)[1]).toEqual(STRADDLE[1]!);
  });

  test("the input array is not mutated", () => {
    const before = structuredClone(STRADDLE);
    moveLeg(STRADDLE, 0, { strike: 25100 }, ROWS);
    expect(STRADDLE).toEqual(before);
  });

  test("a target with no quote leaves the premium absent rather than zero", () => {
    // Unreachable through the slider, which offers only quoted rungs - and asserted
    // anyway, because `legs-url.ts` is explicit that a 0 here analyses a free option.
    // Absent is the honest answer: the server will refuse the Leg, and a refusal beats
    // a curve drawn against a price of nothing.
    const moved = moveLeg(STRADDLE, 0, { strike: 99999 }, ROWS)[0]!;

    expect(moved.strike).toBe(99999);
    expect(moved.entry_premium).toBeUndefined();
  });

  test("an index past the end returns the Strategy unchanged", () => {
    expect(moveLeg(STRADDLE, 7, { strike: 25100 }, ROWS)).toEqual(STRADDLE);
  });

  test("the new strike and its new price both reach the URL", () => {
    // The round trip is what proves the address bar names a position that reproduces.
    // The premium is now written rather than omitted, so the link means the same thing
    // against tomorrow's Chain as it does against this one.
    const url = encodeLegs(moveLeg(STRADDLE, 0, { strike: 25100 }, ROWS));

    expect(url).toBe("25100CE10FEB26S1@360.75,25200PE10FEB26S1@326.7");
    expect(decodeLegs(url)[0]!.entry_premium).toBe(360.75);
  });
});

describe("addLeg", () => {
  const STRADDLE: LegRequest[] = [
    { strike: 25200, option_type: "CE", expiry: EXPIRY, direction: -1, quantity: 1, entry_premium: 344.05 },
  ];

  test("appends a bought call at the strike nearest the Forward, priced from the Chain", () => {
    const added = addLeg(STRADDLE, ROWS, FORWARD, EXPIRY);

    expect(added).toHaveLength(2);
    expect(added[1]).toEqual({
      strike: 25200,
      option_type: "CE",
      expiry: EXPIRY,
      direction: 1,
      quantity: 1,
      entry_premium: 344.05,
    });
  });

  test("nearest the Forward, not nearest Spot", () => {
    // 25,100 is the nearest rung to the anchor's spot of 25,100.25 and 25,200 is the
    // nearest to its Forward. Same rule as the star (#72), and the same rule the ITM
    // wash follows - three places on this screen measure moneyness and they agree.
    expect(addLeg([], ROWS, 25100.25, EXPIRY)[0]!.strike).toBe(25100);
    expect(addLeg([], ROWS, FORWARD, EXPIRY)[0]!.strike).toBe(25200);
  });

  test("the existing Legs come through untouched", () => {
    expect(addLeg(STRADDLE, ROWS, FORWARD, EXPIRY)[0]).toEqual(STRADDLE[0]!);
  });

  test("a Chain quoting no calls adds nothing rather than an unpriceable Leg", () => {
    // The first minute of a date can quote nothing at all. Appending a Leg with no
    // strike would put the whole Strategy into the engine's refusal path, so the button
    // does nothing instead - which the caller renders as a disabled button.
    const noCalls: ChainRow[] = [{ strike: 25300, iv: 0.12, call: null, put: q(402.15) }];
    expect(addLeg(STRADDLE, noCalls, FORWARD, EXPIRY)).toEqual(STRADDLE);
  });
});

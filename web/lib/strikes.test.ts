import { describe, expect, test } from "bun:test";

import { decodeLegs, encodeLegs } from "./legs-url";
import { legalStrikes, nearestIndex, withStrike } from "./strikes";
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
 */

const EXPIRY = "10FEB26";

const quote = { last: 100, open_interest: 0, volume: 0, age_minutes: 0, delta: 0.5 };

const ROWS: ChainRow[] = [
  { strike: 25000, iv: 0.12, call: quote, put: quote },
  { strike: 25100, iv: 0.12, call: quote, put: null }, //   call only
  { strike: 25200, iv: 0.12, call: quote, put: quote },
  { strike: 25300, iv: 0.12, call: null, put: quote }, //   put only
  { strike: 25400, iv: null, call: quote, put: quote }, //  quoted both sides, no vol
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

describe("withStrike", () => {
  const STRADDLE: LegRequest[] = [
    { strike: 25200, option_type: "CE", expiry: EXPIRY, direction: -1, quantity: 1, entry_premium: 344.05 },
    { strike: 25200, option_type: "PE", expiry: EXPIRY, direction: -1, quantity: 1, entry_premium: 326.7 },
  ];

  test("the Entry Premium of the moved Leg is dropped, not carried", () => {
    // The assertion this whole feature turns on. `entry_premium` is optional on the
    // wire, and absent means "read the Chain's last traded price at this strike".
    // Carried, 344.05 would be honoured at the new strike - the server cannot tell a
    // stale premium from a deliberate "what if I had entered at X", because both arrive
    // as a bare float - and the published Breakeven would move to 25,944.05. Wrong,
    // with nothing on screen saying so.
    const moved = withStrike(STRADDLE, 0, 25600);

    expect(moved[0]!.strike).toBe(25600);
    expect(moved[0]!.entry_premium).toBeUndefined();
  });

  test("everything else about the moved Leg survives", () => {
    // Direction is separate from Quantity (CONTEXT.md): sold two is direction -1 and
    // quantity 2, never quantity -2. Losing either here would redraw the curve.
    const moved = withStrike(STRADDLE, 0, 25600)[0]!;

    expect(moved.option_type).toBe("CE");
    expect(moved.direction).toBe(-1);
    expect(moved.quantity).toBe(1);
    expect(moved.expiry).toBe(EXPIRY);
  });

  test("the other Legs are untouched, premium included", () => {
    // Only the Leg being dragged is being repriced. A sibling's Entry Premium may be a
    // deliberate override, and dropping it would silently rewrite a Breakeven the
    // trader set on purpose.
    expect(withStrike(STRADDLE, 0, 25600)[1]).toEqual(STRADDLE[1]!);
  });

  test("the input array is not mutated", () => {
    const before = structuredClone(STRADDLE);
    withStrike(STRADDLE, 0, 25600);
    expect(STRADDLE).toEqual(before);
  });

  test("moving a Leg to the strike it already has changes nothing but the premium", () => {
    // Worth pinning: this is what a drag that returns to its origin does. The premium
    // still goes, and it should - the server will read the same price back off the
    // Chain, so the result is identical without the client having to assert that.
    const same = withStrike(STRADDLE, 0, 25200)[0]!;
    expect(same.strike).toBe(25200);
    expect(same.entry_premium).toBeUndefined();
  });

  test("the dropped premium really leaves the URL", () => {
    // The codec writes `@<premium>` only when the field is present, and warns that a 0
    // there would analyse a free option. So the field must be *absent*, not zero, and
    // this round trip is what proves the difference reaches the address bar.
    const url = encodeLegs(withStrike(STRADDLE, 0, 25600));

    expect(url).toBe("25600CE10FEB26S1,25200PE10FEB26S1@326.7");
    expect(decodeLegs(url)[0]!.entry_premium).toBeUndefined();
  });
});

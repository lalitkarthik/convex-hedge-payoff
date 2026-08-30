import { describe, expect, test } from "bun:test";

import { dropFirst, heldAt } from "./positions";
import type { LegRequest } from "./types";

/**
 * What the Chain already knows about the Strategy, and never showed.
 *
 * The B and S buttons light when the contract beside them is in the position. Two rules
 * decide what "the contract beside them" means, and both are the kind that look like
 * pedantry until they are wrong:
 *
 *  - **Direction is part of the identity here, not part of the quantity.** A bought
 *    25,200 call and a sold one are different positions, so B lights and S does not.
 *    `CONTEXT.md` keeps direction and quantity apart for the same reason.
 *  - **The Expiry is part of the contract** (#71). A strike and a side name two different
 *    instruments once two series trade, and the Chain is showing one of them.
 */

const EXPIRY = "10FEB26";
const OTHER = "24FEB26";

const STRADDLE: LegRequest[] = [
  { strike: 25200, option_type: "CE", expiry: EXPIRY, direction: -1, quantity: 1, entry_premium: 344.05 },
  { strike: 25200, option_type: "PE", expiry: EXPIRY, direction: -1, quantity: 1, entry_premium: 326.7 },
];

describe("heldAt", () => {
  test("the contract in the Strategy is held", () => {
    expect(heldAt(STRADDLE, 25200, "CE", -1, EXPIRY)).toBe(true);
  });

  test("a strike that is not in the Strategy is not", () => {
    expect(heldAt(STRADDLE, 25250, "CE", -1, EXPIRY)).toBe(false);
  });

  test("the right strike on the wrong side is not", () => {
    expect(heldAt([STRADDLE[0]!], 25200, "PE", -1, EXPIRY)).toBe(false);
  });

  test("the right contract in the wrong direction is not", () => {
    // The straddle is sold. B must stay dark on a strike whose S is lit, or the two
    // buttons would say the trader holds both sides of the same contract.
    expect(heldAt(STRADDLE, 25200, "CE", 1, EXPIRY)).toBe(false);
  });

  test("the same strike in another series is not", () => {
    expect(heldAt(STRADDLE, 25200, "CE", -1, OTHER)).toBe(false);
  });
});

describe("dropFirst", () => {
  test("removes the matching Leg", () => {
    expect(dropFirst(STRADDLE, 25200, "CE", -1, EXPIRY)).toEqual([STRADDLE[1]!]);
  });

  test("removes one Leg, not every match", () => {
    // Clicking B twice builds two one-lot Legs, so clicking a lit B takes one off and
    // leaves it lit. Removing both would make the second click undo a click that was
    // never made.
    const doubled = [STRADDLE[0]!, STRADDLE[0]!, STRADDLE[1]!];
    const after = dropFirst(doubled, 25200, "CE", -1, EXPIRY);
    expect(after).toHaveLength(2);
    expect(heldAt(after, 25200, "CE", -1, EXPIRY)).toBe(true);
  });

  test("a Strategy with no match comes back unchanged", () => {
    expect(dropFirst(STRADDLE, 25250, "CE", -1, EXPIRY)).toEqual(STRADDLE);
  });

  test("mutates nothing", () => {
    const before = structuredClone(STRADDLE);
    dropFirst(STRADDLE, 25200, "CE", -1, EXPIRY);
    expect(STRADDLE).toEqual(before);
  });
});

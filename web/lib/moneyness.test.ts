import { describe, expect, test } from "bun:test";

import { inTheMoney } from "./moneyness";

/**
 * Which half of the chain is shaded, and what it is measured against.
 *
 * The wash exists to say **this printed price is probably not a live one**. That is a
 * claim about in-the-money contracts specifically: the model price reproduces the last
 * traded price on 100% of out-of-the-money rows and on only 6.2% of in-the-money ones,
 * because nobody trades the expensive side and the print sits there going stale.
 *
 * The reference is the **Forward**, and that is the only interesting decision in this
 * file. `ADR-0001` and #72 both say the same thing and the ★ already obeys it. The basis
 * reaches +118.87 at the anchor, so Forward and Spot disagree about the moneyness of two
 * whole strikes - which is the difference between a rule and a coincidence.
 */

const FORWARD = 25219.12;
const SPOT = 25100.25;

describe("inTheMoney", () => {
  test("a call below the Forward is in the money", () => {
    expect(inTheMoney(25200, FORWARD, "CE")).toBe(true);
  });

  test("a call above the Forward is not", () => {
    expect(inTheMoney(25250, FORWARD, "CE")).toBe(false);
  });

  test("a put is the mirror of a call", () => {
    expect(inTheMoney(25250, FORWARD, "PE")).toBe(true);
    expect(inTheMoney(25200, FORWARD, "PE")).toBe(false);
  });

  test("a strike exactly at the Forward is neither", () => {
    // Strict both ways, so no strike is ever washed on both sides at once. Nothing
    // quotes at 25,219.12, but a Forward that lands on the grid is one fit away.
    expect(inTheMoney(FORWARD, FORWARD, "CE")).toBe(false);
    expect(inTheMoney(FORWARD, FORWARD, "PE")).toBe(false);
  });

  test("the Forward decides, not Spot", () => {
    // 25,200 is the starred strike: below the Forward of 25,219.12 and above the Spot
    // of 25,100.25, so the two references disagree about it. This is the test that
    // fails if anyone reaches for `chain.spot`, which is right there on the same object.
    expect(inTheMoney(25200, FORWARD, "CE")).toBe(true);
    expect(inTheMoney(25200, SPOT, "CE")).toBe(false);
  });
});

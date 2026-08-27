import { describe, expect, test } from "bun:test";

import { LegsUrlError, decodeLegs, encodeLegs } from "./legs-url";

/**
 * The Strategy lives in the address bar, so this codec **is** the state model (#32).
 *
 * Two properties matter more than the spelling of the format. A Strategy that survives
 * a copy-paste into a fresh tab is the whole feature; and a malformed link must fail
 * loudly, because the alternative is dropping a leg silently and showing a trader a
 * chart of a position they did not build.
 */

const EXPIRY = "10FEB26";

const STRADDLE = [
  { strike: 25200, option_type: "CE", expiry: EXPIRY, direction: -1, quantity: 1, entry_premium: 344.05 },
  { strike: 25200, option_type: "PE", expiry: EXPIRY, direction: -1, quantity: 1, entry_premium: 326.7 },
] as const;

describe("round trip", () => {
  test("the anchor straddle survives encode and decode unchanged", () => {
    expect(decodeLegs(encodeLegs([...STRADDLE]))).toEqual([...STRADDLE]);
  });

  test("quantity and entry premium both survive", () => {
    const legs = [
      { strike: 25000, option_type: "CE" as const, expiry: EXPIRY, direction: 1 as const, quantity: 7, entry_premium: 459.25 },
    ];
    expect(decodeLegs(encodeLegs(legs))).toEqual(legs);
  });

  test("a fractional strike survives", () => {
    // Not in this dataset, but the wire type is a float and the codec must not assume
    // otherwise - a codec that silently rounds is worse than one that refuses.
    const legs = [
      { strike: 25012.5, option_type: "PE" as const, expiry: EXPIRY, direction: -1 as const, quantity: 1, entry_premium: 12.5 },
    ];
    expect(decodeLegs(encodeLegs(legs))).toEqual(legs);
  });

  test("order is preserved, because the Greeks table is read beside the Legs", () => {
    const reversed = [...STRADDLE].reverse();
    expect(decodeLegs(encodeLegs(reversed))[0].option_type).toBe("PE");
  });

  test("an empty Strategy encodes to an empty string and back", () => {
    expect(encodeLegs([])).toBe("");
    expect(decodeLegs("")).toEqual([]);
    expect(decodeLegs(null)).toEqual([]);
  });
});

describe("the encoding a human will read in the address bar", () => {
  test("is the contract, then how it was traded", () => {
    // Strike, type and Expiry name the instrument; side, quantity and premium say what
    // was done with it. The Expiry sits between the two halves for that reason (#71).
    expect(encodeLegs([...STRADDLE])).toBe(
      "25200CE10FEB26S1@344.05,25200PE10FEB26S1@326.7",
    );
  });

  test("B and S rather than 1 and -1, because a URL is read by people", () => {
    const bought = [{ ...STRADDLE[0], direction: 1 as const }];
    expect(encodeLegs(bought)).toContain("10FEB26B1");
  });
});

describe("malformed input fails loudly", () => {
  // The whole point. A link that has been truncated by a chat client, or hand-edited,
  // must not quietly analyse a subset of what it names.
  test.each([
    ["a missing option type", "2520010FEB26B1@344.05"],
    ["an unknown option type", "25200XX10FEB26B1@344.05"],
    ["a missing direction", "25200CE10FEB261@344.05"],
    ["a non-numeric strike", "abcCE10FEB26B1@344.05"],
    ["a zero quantity", "25200CE10FEB26B0@344.05"],
    ["a negative quantity", "25200CE10FEB26B-2@344.05"],
    ["a fractional quantity", "25200CE10FEB26B1.5@344.05"],
    ["a truncated premium", "25200CE10FEB26B1@"],
    ["one good leg and one broken", "25200CE10FEB26B1@344.05,garbage"],
    // A Leg with no Expiry is the pre-#71 spelling, and it is refused rather than
    // filled in from the view: the ambiguity is the whole reason the field exists, and
    // a link that resolved it silently would put a trader in a series they did not pick.
    ["a Leg with no Expiry", "25200CEB1@344.05"],
    ["an Expiry that is not a date", "25200CEXXXXXXXB1@344.05"],
    // Note what is *not* here: `10ABC26` decodes. The shape is checked, the month name
    // is not - `catalog.MONTHS` is the one table that knows which three letters are a
    // month, and a second copy of it in TypeScript is a copy that can disagree. A link
    // holding one comes back 422 from `/analyse`, naming the form it expected.
  ])("rejects %s", (_name, encoded) => {
    expect(() => decodeLegs(encoded)).toThrow(LegsUrlError);
  });

  test("the error names the fragment that failed, not just 'invalid'", () => {
    try {
      decodeLegs("25200CE10FEB26B1@344.05,garbage");
      throw new Error("should have thrown");
    } catch (error) {
      expect(error).toBeInstanceOf(LegsUrlError);
      expect((error as LegsUrlError).message).toContain("garbage");
    }
  });

  test("never returns a partial Strategy", () => {
    // The failure this guards is the quiet one: nine legs in the link, eight on screen,
    // and a chart that is wrong in a way nothing announces.
    let decoded: unknown = "not assigned";
    try {
      decoded = decodeLegs("25200CE10FEB26B1@344.05,garbage");
    } catch {
      /* expected */
    }
    expect(decoded).toBe("not assigned");
  });
});

describe("entry premium is optional", () => {
  test("a leg with no premium decodes with it absent, for the server to fill in", () => {
    // LegRequest.entry_premium is nullable precisely so the server can use the Chain's
    // last traded price. A codec that invented 0 here would analyse a free option.
    const [leg] = decodeLegs("25200CE10FEB26B1");
    expect(leg.entry_premium).toBeUndefined();
    expect(leg.strike).toBe(25200);
    expect(leg.expiry).toBe("10FEB26");
  });

  test("and re-encodes without one", () => {
    expect(encodeLegs(decodeLegs("25200CE10FEB26B1"))).toBe("25200CE10FEB26B1");
  });
});

describe("the Expiry a Leg carries", () => {
  // #71: a Leg names its own series. Everything below is about that being genuinely
  // per-Leg rather than one value applied to all of them at the edges of the codec.

  test("survives the round trip on every Leg, not merely on the first", () => {
    const spanning = [
      { strike: 25200, option_type: "CE" as const, expiry: "10FEB26", direction: 1 as const, quantity: 1 },
      { strike: 25200, option_type: "PE" as const, expiry: "24FEB26", direction: -1 as const, quantity: 1 },
    ];
    expect(decodeLegs(encodeLegs(spanning))).toEqual(spanning);
  });

  test("is carried rather than judged — the engine is what refuses a calendar", () => {
    // The codec's job is to say what the link names. A Strategy spanning two Expiries is
    // refused by `/analyse`, which is the only place that knows there is no Expiry line
    // to draw for it — and refusing it here as well would mean two rules to keep in step,
    // with the URL's one silently deciding what the engine never saw.
    const [near, far] = decodeLegs("25200CE10FEB26B1,25200PE24FEB26S1");
    expect(near.expiry).toBe("10FEB26");
    expect(far.expiry).toBe("24FEB26");
  });
});

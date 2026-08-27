/**
 * The Strategy, as a string in the address bar.
 *
 * **State lives in the URL, not in a store** (#32). Four pieces of state do not justify
 * one, and the payoff is immediate: a Strategy is a link, so `/analyse?…` can be opened
 * cold, refreshed, or pasted to a reviewer, and it reproduces the identical chart.
 *
 * The format is meant to be *read* by a person glancing at the address bar:
 *
 *     25200CE10FEB26S1@344.05,25200PE10FEB26S1@326.7
 *     └──┬──┘└┤└──┬──┘││└─┬─┘
 *      strike │   │   ││  └── entry premium, optional - absent means "use the Chain's last"
 *             │   │   │└───── quantity, a positive integer
 *             │   │   └────── B bought, S sold
 *             │   └────────── Expiry, as the dropdown and `/chain` spell it
 *             └────────────── CE or PE
 *
 * Strike, type and Expiry together are the **contract**; side, quantity and premium are
 * how it was traded. The Expiry joined them with #71, and it is required rather than
 * inherited from the `?expiry=` the view carries: a Leg names its own series, and a Leg
 * that took the view's would change instrument when the trader changed the dropdown.
 *
 * The label is fixed-width — two digits, three letters, two digits — so it needs no
 * delimiter to be told apart from the quantity that follows it.
 *
 * **A malformed link throws.** That is the entire design rule here. The tempting
 * alternative - skip the fragments that do not parse - shows a trader a chart of eight
 * legs when their link named nine, and nothing on screen says so. #23's error contract
 * would rather fail at the URL than lie about the position.
 */

import type { LegRequest, OptionType } from "./types";

/** Thrown for any input that is not a complete, well-formed Strategy. */
export class LegsUrlError extends Error {
  constructor(fragment: string, reason: string) {
    super(`cannot read "${fragment}" as a Leg: ${reason}`);
    this.name = "LegsUrlError";
  }
}

const LEG = /^(\d+(?:\.\d+)?)(CE|PE)(\d{2}[A-Z]{3}\d{2})([BS])(\d+)(?:@(\d+(?:\.\d+)?))?$/;

export function encodeLegs(legs: LegRequest[]): string {
  return legs
    .map((leg) => {
      const side = leg.direction === 1 ? "B" : "S";
      const premium =
        leg.entry_premium === undefined || leg.entry_premium === null
          ? ""
          : `@${leg.entry_premium}`;
      return `${leg.strike}${leg.option_type}${leg.expiry}${side}${leg.quantity ?? 1}${premium}`;
    })
    .join(",");
}

/**
 * All of the Legs, or none of them and an exception.
 *
 * Parsed into a local array and returned only at the end, so a throw half way through
 * cannot leave a caller holding a partial Strategy.
 */
export function decodeLegs(encoded: string | null | undefined): LegRequest[] {
  if (!encoded) return [];

  const legs: LegRequest[] = [];
  for (const fragment of encoded.split(",")) {
    const match = LEG.exec(fragment);
    if (!match) {
      throw new LegsUrlError(
        fragment,
        "expected <strike><CE|PE><expiry><B|S><quantity>[@<premium>], as in 25200CE10FEB26B1",
      );
    }

    const [, strike, optionType, expiry, side, quantity, premium] = match;
    if (Number(quantity) < 1) {
      throw new LegsUrlError(fragment, "quantity is at least one; the sign lives in B or S");
    }

    legs.push({
      strike: Number(strike),
      option_type: optionType as OptionType,
      expiry,
      direction: side === "B" ? 1 : -1,
      quantity: Number(quantity),
      // Left absent rather than defaulted: `LegRequest.entry_premium` is nullable so the
      // server can fill it from the Chain's last traded price, and a 0 here would
      // analyse a free option.
      ...(premium === undefined ? {} : { entry_premium: Number(premium) }),
    });
  }
  return legs;
}

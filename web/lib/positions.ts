import type { Direction, LegRequest, OptionType } from "@/lib/types";

/**
 * Which contracts the Chain's buttons should be showing as already held.
 *
 * The Chain has had the Strategy in its hands the whole time and rendered none of it
 * onto the table, so a strike already in the position looked exactly like one that was
 * not. These two functions are the whole of that feature; the buttons just read them.
 *
 * **A contract is a strike, a side and an Expiry** (#71) - and here, a direction too.
 * Bought and sold are different positions, not one position with a sign, which is the
 * same separation `CONTEXT.md` insists on between direction and quantity. So B and S
 * light independently and never both.
 */

function matches(
  leg: LegRequest,
  strike: number,
  optionType: OptionType,
  direction: Direction,
  expiry: string,
): boolean {
  return (
    leg.strike === strike &&
    leg.option_type === optionType &&
    leg.direction === direction &&
    leg.expiry === expiry
  );
}

/** Whether this exact contract, traded this way, is anywhere in the Strategy. */
export function heldAt(
  legs: LegRequest[],
  strike: number,
  optionType: OptionType,
  direction: Direction,
  expiry: string,
): boolean {
  return legs.some((leg) => matches(leg, strike, optionType, direction, expiry));
}

/**
 * The Strategy with **one** matching Leg removed.
 *
 * One, not all of them. Clicking B twice on the same strike builds two one-lot Legs, so
 * a click on the lit button has to take one back off and leave the button lit - the
 * alternative undoes a click the trader never made. It also means B never stops being
 * additive, which is what keeps a two-lot position expressible from the Chain at all.
 *
 * Quantity is deliberately not consulted. A Leg's quantity is edited in the Legs strip;
 * this is the button that put the Leg there taking it away again.
 */
export function dropFirst(
  legs: LegRequest[],
  strike: number,
  optionType: OptionType,
  direction: Direction,
  expiry: string,
): LegRequest[] {
  const at = legs.findIndex((leg) => matches(leg, strike, optionType, direction, expiry));
  return at === -1 ? legs : [...legs.slice(0, at), ...legs.slice(at + 1)];
}

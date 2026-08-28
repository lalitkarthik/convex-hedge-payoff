import type { ChainRow, LegRequest, OptionType } from "@/lib/types";

/**
 * The strike ladder, and what moving along it does to a Leg.
 *
 * All of it pure, and deliberately so: the rules that decide which strikes a trader may
 * reach are the rules that decide whether the engine can answer, and those are worth
 * testing without a browser between them and the assertion.
 */

/**
 * The strikes a Leg of this type can be moved to, at this minute, ascending.
 *
 * These are exactly the two conditions `chain.resolve_legs` applies - the
 * `(strike, option_type)` pair must be in the minute's snapshot, and the strike must
 * carry an implied volatility - so **the set the slider can reach is the set the engine
 * can price.** That equality is the whole reason the slider cannot produce a refusal.
 *
 * Both halves matter and the second is the forgettable one: a strike may be quoted on
 * both sides and still carry no volatility, as every strike does in the last minute of
 * Expiry day, and it looks perfectly healthy on the Chain while doing it.
 *
 * The ladder is per-side. Fifty of the anchor's ninety-one strikes quote one side only,
 * so a call and a put at the same minute genuinely have different ladders.
 */
export function legalStrikes(rows: ChainRow[], optionType: OptionType): number[] {
  return rows
    .filter((row) => row.iv !== null && (optionType === "CE" ? row.call : row.put) !== null)
    .map((row) => row.strike)
    .sort((a, b) => a - b);
}

/**
 * Where a Leg's strike sits on the ladder, or the nearest rung to it.
 *
 * Not `indexOf`, because a Leg's strike can legitimately be absent: it was quoted at
 * the minute the Leg was built, the trader moved the time control, and at this minute
 * it has not printed. `indexOf` answers -1 there, which would park the thumb at the far
 * left and say the Leg is the lowest strike on the board.
 *
 * Ties resolve to the lower rung. Which one is arbitrary; that it is the *same* one on
 * every render is not, or the thumb would jitter between two positions with nothing
 * having changed. Strict `<` gives that for free by keeping the first winner.
 */
export function nearestIndex(strikes: number[], strike: number): number {
  let best = 0;
  for (let i = 1; i < strikes.length; i++) {
    if (Math.abs(strikes[i]! - strike) < Math.abs(strikes[best]! - strike)) best = i;
  }
  return best;
}

/**
 * The Strategy with one Leg moved to another strike.
 *
 * **The Entry Premium goes with the move.** `entry_premium` is optional on the wire and
 * absent means "read the Chain's last traded price", so dropping it is what makes the
 * server reprice the Leg where it now sits. Carrying it would be silently wrong: the
 * engine cannot tell a premium left over from the old strike from a deliberate "what if
 * I had entered at X", because both arrive as a bare float. A short 25,200 call dragged
 * to 25,600 while still claiming 344.05 publishes a Breakeven of 25,944.05, and nothing
 * on the screen would contradict it.
 *
 * Dropped by omission rather than set to 0 - `legs-url.ts` is explicit that a zero here
 * would analyse a free option.
 *
 * Only the moved Leg is touched. A sibling's premium may be an override the trader set
 * on purpose, and this is not the action that revokes it.
 */
export function withStrike(legs: LegRequest[], at: number, strike: number): LegRequest[] {
  return legs.map((leg, index) => {
    if (index !== at) return leg;
    const { entry_premium: _dropped, ...rest } = leg;
    return { ...rest, strike };
  });
}

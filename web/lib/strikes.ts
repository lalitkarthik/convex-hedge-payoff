import type { ChainQuote, ChainRow, LegRequest, OptionType } from "@/lib/types";

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

/** The quote for one contract, or null - never the other side's, and never a zero. */
export function quoteAt(
  rows: ChainRow[],
  strike: number,
  optionType: OptionType,
): ChainQuote | null {
  const row = rows.find((candidate) => candidate.strike === strike);
  if (!row) return null;
  return (optionType === "CE" ? row.call : row.put) ?? null;
}

/**
 * The Strategy with one Leg moved - to another strike, to the other side, or both.
 *
 * **The Entry Premium never travels with the Leg.** `entry_premium` arrives at the
 * server as a bare float, so it cannot tell a premium left over from the old strike from
 * a deliberate "what if I had entered at X" (story 18). A short 25,200 call dragged to
 * 25,600 while still claiming 344.05 publishes a Breakeven of 25,944.05, and nothing on
 * the screen would contradict it.
 *
 * It used to be **dropped** for that reason, which was right while this page could not
 * see the Chain: absent means "server, read the last traded price at this strike", and
 * the server would find the right number. It is **replaced** now, because Analyse
 * fetches the Chain and can say the price rather than ask for it. Same guarantee, and
 * the box on screen shows 88.20 instead of a placeholder where a price should be.
 *
 * Where there is no quote at all the field is left absent rather than set to 0 -
 * `legs-url.ts` is explicit that a zero there analyses a free option. Unreachable
 * through the slider, which offers only quoted rungs.
 *
 * **A side change snaps the strike.** The ladders are per-side and 50 of the anchor's 91
 * strikes quote one side only, so keeping the strike across a flip would land the Leg on
 * a contract the engine cannot price. The strike alone is never snapped: it comes from
 * the slider, which offers nothing else.
 *
 * Only the addressed Leg is touched. A sibling's premium may be an override the trader
 * set on purpose, and this is not the action that revokes it.
 */
export function moveLeg(
  legs: LegRequest[],
  at: number,
  patch: { strike?: number; option_type?: OptionType },
  rows: ChainRow[],
): LegRequest[] {
  const leg = legs[at];
  if (!leg) return legs;

  const optionType = patch.option_type ?? leg.option_type;
  let strike = patch.strike ?? leg.strike;

  if (optionType !== leg.option_type) {
    const ladder = legalStrikes(rows, optionType);
    strike = ladder[nearestIndex(ladder, strike)] ?? strike;
  }

  const quote = quoteAt(rows, strike, optionType);
  const { entry_premium: _replaced, ...rest } = leg;
  const moved: LegRequest = {
    ...rest,
    strike,
    option_type: optionType,
    ...(quote === null ? {} : { entry_premium: quote.last }),
  };

  return legs.map((existing, index) => (index === at ? moved : existing));
}

/**
 * The Strategy with one more Leg on it: a bought call at the money, priced from the Chain.
 *
 * At the money means **nearest the Forward**, which is the rule the starred strike and
 * the in-the-money wash both follow (#72, ADR-0001). Nearest Spot would pick a different
 * strike - the basis reaches +118.87 - and three places on this screen measuring
 * moneyness three ways would be worse than any one of them being wrong.
 *
 * It lands mid-ladder so it can be dragged in either direction, and bought rather than
 * sold because a position that starts with unlimited loss is a poor thing to hand
 * somebody who has not chosen a direction yet.
 *
 * A Chain quoting no calls at this minute adds nothing at all. Appending a Leg with no
 * price would put the whole Strategy into the engine's refusal path, taking the chart
 * away as the cost of a click.
 */
export function addLeg(
  legs: LegRequest[],
  rows: ChainRow[],
  forward: number,
  expiry: string,
): LegRequest[] {
  const ladder = legalStrikes(rows, "CE");
  const strike = ladder[nearestIndex(ladder, forward)];
  if (strike === undefined) return legs;

  const quote = quoteAt(rows, strike, "CE");
  return [
    ...legs,
    {
      strike,
      option_type: "CE",
      expiry,
      direction: 1,
      quantity: 1,
      ...(quote === null ? {} : { entry_premium: quote.last }),
    },
  ];
}

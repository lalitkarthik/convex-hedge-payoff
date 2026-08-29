"use client";

import { useEffect, useRef } from "react";

import type {
  ChainResponse,
  ChainRow,
  ChainQuote,
  Direction,
  LegRequest,
  OptionType,
} from "@/lib/types";
import { count, greek, price, strike as fmtStrike, volatility } from "@/lib/format";
import { inTheMoney } from "@/lib/moneyness";
import { heldAt } from "@/lib/positions";

/**
 * Calls left, puts right, strikes down the middle, **one shared IV column**.
 *
 * One volatility per strike and none per side, because that is what it is: solved from
 * the out-of-the-money leg and shared with its in-the-money twin, whose last print is
 * stale. Served as-of, only 9 of the anchor's 41 both-sided strikes have both legs from
 * the same minute — so "the call and put carry equal IV" cannot hold as a per-side
 * guarantee, and a single number cannot disagree with itself (#28).
 *
 * Three rules this table must not break:
 *
 *  - **A missing side renders blank.** Never a zero, never a dash that could read as a
 *    price. It is hatched, so absence looks deliberate.
 *  - **Quote age is visible**, not merely available. It reaches 153 minutes at the wings
 *    and presenting that as live would be dishonest rather than imprecise. Rows past an
 *    hour are dimmed; #31 owns the real threshold.
 *  - **The starred strike is nearest the Forward**, not nearest spot — 25,200 against
 *    25,100 at the anchor.
 *
 * The in-the-money half carries a red wash, and it is a claim about the **price** rather
 * than about the position: the model reproduces `last` on 100% of out-of-the-money rows
 * and on 6.2% of in-the-money ones, so the shaded side is the side whose print is least
 * likely to still be live. It is a wash and not a veil — every figure stays at full
 * contrast. Measured against the Forward, by the rule the star already follows
 * (`lib/moneyness.ts`).
 *
 * A **B or S already in the Strategy is lit**, and clicking a lit one takes that Leg
 * back off. The Chain has been holding the Legs all along and rendering none of them
 * onto the table, so a strike already in the position looked exactly like one that was
 * not. The lit treatment is the hover treatment made permanent, so there is nothing new
 * to learn - see `lib/positions.ts` for what counts as the same contract.
 */

const STALE_MINUTES = 60;

function QuoteCells({
  quote,
  side,
  strike,
  forward,
  expiry,
  legs,
  onPick,
}: {
  quote: ChainQuote | null;
  side: OptionType;
  strike: number;
  forward: number;
  expiry: string;
  legs: LegRequest[];
  onPick: (strike: number, optionType: OptionType, direction: Direction) => void;
}) {
  if (!quote) {
    return (
      <>
        <td className="blank" />
        <td className="blank" />
        <td className="blank" />
        <td className="blank" />
        <td className="blank" />
      </>
    );
  }

  const stale = quote.age_minutes >= STALE_MINUTES ? "stale" : "";
  // Computed after the blank-side return above, and deliberately: an unquoted side is
  // left unwashed, because there is no contract there and shading an absence would be
  // making a claim about a price that was never printed.
  const itm = inTheMoney(strike, forward, side) ? "itm" : "";
  // The Expiry comes off the response rather than off the URL: a Leg names its own
  // series, and the two differ for as long as it takes the engine to resolve a stale
  // link. Lighting a button against the wrong series would claim a position in an
  // instrument that is not on screen.
  const bought = heldAt(legs, strike, side, 1, expiry);
  const sold = heldAt(legs, strike, side, -1, expiry);
  const buttons = (
    <td className={itm}>
      <span className="bs">
        <button
          className={`buy ${bought ? "on" : ""}`}
          onClick={() => onPick(strike, side, 1)}
          title={bought ? "Bought — click to remove" : "Buy"}
          aria-pressed={bought}
        >
          B
        </button>
        <button
          className={`sell ${sold ? "on" : ""}`}
          onClick={() => onPick(strike, side, -1)}
          title={sold ? "Sold — click to remove" : "Sell"}
          aria-pressed={sold}
        >
          S
        </button>
      </span>
    </td>
  );

  const cells = [
    <td key="oi" className={`num ${stale} ${itm}`}>{count(quote.open_interest)}</td>,
    <td key="vol" className={`num ${stale} ${itm}`}>{count(quote.volume)}</td>,
    <td key="d" className={`num ${stale} ${itm}`}>{quote.delta === null ? "" : greek("delta", quote.delta)}</td>,
    <td key="ltp" className={`num ${stale} ${itm}`}>
      {price(quote.last)}
      {quote.age_minutes > 0 && <span className="age"> {quote.age_minutes}m</span>}
    </td>,
  ];

  // Calls read outward-in from the left, puts inward-out to the right, so the two
  // columns nearest the strike are always the traded prices.
  return side === "CE" ? (
    <>
      {cells[0]}
      {cells[1]}
      {cells[2]}
      {cells[3]}
      {buttons}
    </>
  ) : (
    <>
      {buttons}
      {cells[3]}
      {cells[2]}
      {cells[1]}
      {cells[0]}
    </>
  );
}

export default function ChainTable({
  chain,
  atTheMoney,
  legs,
  onPick,
}: {
  chain: ChainResponse;
  atTheMoney: number;
  legs: LegRequest[];
  onPick: (strike: number, optionType: OptionType, direction: Direction) => void;
}) {
  const money = useRef<HTMLTableRowElement>(null);

  // Open on the money. The chain spans 23,300 to 27,950 and the interesting strikes are
  // in the middle, so a table scrolled to its top shows forty rows of deep out-of-the-
  // money puts and an empty call side - which reads as broken rather than as far away.
  //
  // On mount only. Re-centring every time the time control moves would yank the view
  // out from under someone reading a wing.
  useEffect(() => {
    money.current?.scrollIntoView({ block: "center" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="chain-wrap">
      <table className="chain">
        <thead>
          <tr>
            <th className="side-head side-call" colSpan={5}>
              Calls
            </th>
            <th className="side-head" colSpan={2}>
              Strike
            </th>
            <th className="side-head side-put" colSpan={5}>
              Puts
            </th>
          </tr>
          <tr>
            <th>OI</th>
            <th>Vol</th>
            <th>Δ</th>
            <th>LTP</th>
            <th />
            <th style={{ textAlign: "center" }}>Strike</th>
            <th style={{ textAlign: "center" }}>IV</th>
            <th />
            <th>LTP</th>
            <th>Δ</th>
            <th>Vol</th>
            <th>OI</th>
          </tr>
        </thead>
        <tbody>
          {chain.rows.map((row: ChainRow) => (
            <tr
              key={row.strike}
              ref={row.strike === atTheMoney ? money : undefined}
              className={row.strike === atTheMoney ? "at-the-money" : ""}
            >
              <QuoteCells
                quote={row.call}
                side="CE"
                strike={row.strike}
                forward={chain.forward}
                expiry={chain.expiry}
                legs={legs}
                onPick={onPick}
              />
              <td className="strike">
                {fmtStrike(row.strike)}
                {row.strike === atTheMoney && " ★"}
              </td>
              <td className="iv">{volatility(row.iv)}</td>
              <QuoteCells
                quote={row.put}
                side="PE"
                strike={row.strike}
                forward={chain.forward}
                expiry={chain.expiry}
                legs={legs}
                onPick={onPick}
              />
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

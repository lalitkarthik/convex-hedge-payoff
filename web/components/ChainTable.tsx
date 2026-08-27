"use client";

import { useEffect, useRef } from "react";

import type { ChainResponse, ChainRow, ChainQuote, Direction, OptionType } from "@/lib/types";
import { count, greek, price, strike as fmtStrike, volatility } from "@/lib/format";

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
 */

const STALE_MINUTES = 60;

function QuoteCells({
  quote,
  side,
  strike,
  onPick,
}: {
  quote: ChainQuote | null;
  side: OptionType;
  strike: number;
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
  const buttons = (
    <td>
      <span className="bs">
        <button className="buy" onClick={() => onPick(strike, side, 1)} title="Buy">
          B
        </button>
        <button className="sell" onClick={() => onPick(strike, side, -1)} title="Sell">
          S
        </button>
      </span>
    </td>
  );

  const cells = [
    <td key="oi" className={`num ${stale}`}>{count(quote.open_interest)}</td>,
    <td key="vol" className={`num ${stale}`}>{count(quote.volume)}</td>,
    <td key="d" className={`num ${stale}`}>{quote.delta === null ? "" : greek("delta", quote.delta)}</td>,
    <td key="ltp" className={`num ${stale}`}>
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
  onPick,
}: {
  chain: ChainResponse;
  atTheMoney: number;
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
              <QuoteCells quote={row.call} side="CE" strike={row.strike} onPick={onPick} />
              <td className="strike">
                {fmtStrike(row.strike)}
                {row.strike === atTheMoney && " ★"}
              </td>
              <td className="iv">{volatility(row.iv)}</td>
              <QuoteCells quote={row.put} side="PE" strike={row.strike} onPick={onPick} />
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

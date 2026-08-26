import type { Greeks, Leg } from "@/lib/types";
import { greek, strike as fmtStrike } from "@/lib/format";

/**
 * One row per Leg, in the order they were built, plus a total.
 *
 * **Per contract** — no Lot Size and no number of lots. Those are presentation
 * multipliers (#29), and a Greek carrying them could not be compared against another
 * Strategy's. The per-Leg rows *are* signed by direction and quantity, because that is
 * what a per-Leg exposure means to whoever reads it beside the Legs.
 *
 * Two conventions that surprise (#53, `calculations.md` §5):
 *
 *  - **Delta and gamma are discounted.** A call's delta is bounded by the discount
 *    factor rather than by 1 — a delta of exactly 1 would mean an undiscounted payoff.
 *  - **Theta is a one-session repricing**, already scaled. Do not divide by 252 again.
 *
 * Nothing here computes a Greek. These are per-contract values the engine produced,
 * multiplied by direction and quantity — arithmetic, not pricing.
 */
const NAMES: (keyof Greeks)[] = ["delta", "gamma", "vega", "theta", "rho"];

export default function GreeksTable({
  legs,
  rows,
  total,
}: {
  legs: Leg[];
  rows: (Greeks | null)[];
  total: Greeks | null;
}) {
  return (
    <table className="grid">
      <thead>
        <tr>
          <th>Leg</th>
          <th>Δ</th>
          <th>Γ</th>
          <th>ν</th>
          <th>Θ</th>
          <th>ρ</th>
        </tr>
      </thead>
      <tbody>
        {legs.map((leg, index) => (
          <tr key={`${leg.strike}${leg.optionType}${index}`}>
            <td>
              {leg.direction === 1 ? "B" : "S"} {leg.quantity}× {fmtStrike(leg.strike)}{" "}
              {leg.optionType}
            </td>
            {NAMES.map((name) => (
              <td key={name} className="num">
                {rows[index] ? greek(name, rows[index]![name]) : "—"}
              </td>
            ))}
          </tr>
        ))}
        {total && (
          <tr className="total">
            <td>Total</td>
            {NAMES.map((name) => (
              <td key={name} className="num">
                {greek(name, total[name])}
              </td>
            ))}
          </tr>
        )}
      </tbody>
    </table>
  );
}

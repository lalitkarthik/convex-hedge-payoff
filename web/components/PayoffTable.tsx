import type { CurvePoint } from "@/lib/skeleton-maths";
import { level, price } from "@/lib/format";

/**
 * P&L at expiry across the strike grid, in 50-point steps — the interval this chain
 * actually trades on, so every row is a spot a strike exists at.
 *
 * The row nearest spot is highlighted, and it must agree with the chart read at the same
 * spot. Both come from the same function, which is what makes that agreement structural
 * rather than a coincidence worth checking.
 */
export default function PayoffTable({ rows, spot }: { rows: CurvePoint[]; spot: number }) {
  const nearest = rows.reduce(
    (best, row) => (Math.abs(row.spot - spot) < Math.abs(best.spot - spot) ? row : best),
    rows[0],
  );

  return (
    <table className="grid">
      <thead>
        <tr>
          <th>Spot at expiry</th>
          <th>Move</th>
          <th>P&amp;L</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.spot} className={row === nearest ? "here" : ""}>
            <td>{level(row.spot)}</td>
            <td className="num" style={{ color: "var(--ink-faint)" }}>
              {(((row.spot - spot) / spot) * 100).toFixed(1)}%
            </td>
            <td className={`num ${row.pnl >= 0 ? "gain" : "loss"}`}>{price(row.pnl)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

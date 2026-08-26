import type { Curve } from "@/lib/types";
import { level, price } from "@/lib/format";

/**
 * P&L at expiry across the strike grid, in 50-point steps — the interval this chain
 * actually trades on, so every row is a spot a strike exists at.
 *
 * **These rows are the server's** (#29). They used to be computed here, which meant the
 * table and the chart were two implementations of one quantity and free to drift; now
 * they arrive in the same response and `tests/test_api_table.py` asserts they lie on the
 * same line. The row nearest spot is highlighted, and the highlight is the only decision
 * this component makes.
 */
export default function PayoffTable({ table, spot }: { table: Curve; spot: number }) {
  const rows = table.spot.map((value, index) => ({
    spot: value,
    pnl: table.pnl_at_expiry[index],
  }));

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

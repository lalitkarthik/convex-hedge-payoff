import type { Curve } from "@/lib/types";
import { level, price } from "@/lib/format";

/**
 * P&L at expiry across the strike grid, in 50-point steps — the interval this chain
 * actually trades on, so every row is a Forward a strike exists at.
 *
 * **The rows are Forwards** (#72, `CONTEXT.md`), which is what the column now says. It
 * said "Spot at expiry" over these same numbers, and the two converge at Expiry — which
 * is exactly why the wrong label survived: defensible at one instant, and wrong on the
 * whole way there, where the basis is +118.87.
 *
 * **These rows are the server's** (#29). They used to be computed here, which meant the
 * table and the chart were two implementations of one quantity and free to drift; now
 * they arrive in the same response and `tests/test_api_table.py` asserts they lie on the
 * same line. The row nearest the Forward is highlighted, and the highlight is the only
 * decision this component makes.
 */
export default function PayoffTable({ table, forward }: { table: Curve; forward: number }) {
  const rows = table.forward.map((value, index) => ({
    forward: value,
    pnl: table.pnl_at_expiry[index],
  }));

  const nearest = rows.reduce(
    (best, row) =>
      Math.abs(row.forward - forward) < Math.abs(best.forward - forward) ? row : best,
    rows[0],
  );

  return (
    <table className="grid">
      <thead>
        <tr>
          <th>Forward at expiry</th>
          <th>Move</th>
          <th>P&amp;L</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.forward} className={row === nearest ? "here" : ""}>
            <td>{level(row.forward)}</td>
            <td className="num" style={{ color: "var(--ink-faint)" }}>
              {(((row.forward - forward) / forward) * 100).toFixed(1)}%
            </td>
            <td className={`num ${row.pnl >= 0 ? "gain" : "loss"}`}>{price(row.pnl)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

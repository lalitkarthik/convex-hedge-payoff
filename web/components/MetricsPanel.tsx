import type { Metrics } from "@/lib/types";
import { bound, level, price, ratio } from "@/lib/format";

/**
 * The four numbers under the chart, and the ratio between two of them.
 *
 * Every one is a property of the Legs **at expiry**. Two conventions worth stating where
 * they are read:
 *
 *  - **Net Premium is signed**: positive is paid out (a debit), negative is received (a
 *    credit). `CONTEXT.md` signs it that way and nothing here re-signs it.
 *  - **An absent bound is the word "Unlimited"** — never `∞`, never blank, never a very
 *    large number, all three of which read as a value. Only the upside can be unbounded:
 *    the Forward cannot fall below zero, so the left-hand tail always terminates. The
 *    Forward, because that is what the axis these bounds are read off is measured in
 *    (#72, `CONTEXT.md`) — the same sentence used to say spot.
 *
 * Reward/risk is not-applicable when either side is Unlimited. A ratio against an
 * unlimited gain has no meaning, and printing a big number instead would read as a good
 * trade.
 */
export default function MetricsPanel({ metrics }: { metrics: Metrics }) {
  const credit = metrics.net_premium < 0;

  return (
    <table className="kv">
      <tbody>
        <tr>
          <td>Max profit</td>
          <td className="num gain">{bound(metrics.max_profit)}</td>
        </tr>
        <tr>
          <td>Max loss</td>
          <td className="num loss">{bound(metrics.max_loss)}</td>
        </tr>
        <tr>
          <td>Breakevens</td>
          <td className="num">
            {metrics.breakevens.length === 0
              ? "none"
              : metrics.breakevens.map((value) => level(value)).join("  ·  ")}
          </td>
        </tr>
        <tr>
          <td>Net premium</td>
          <td className="num">
            {price(Math.abs(metrics.net_premium))}{" "}
            <span style={{ color: "var(--ink-faint)" }}>{credit ? "credit" : "debit"}</span>
          </td>
        </tr>
        <tr>
          <td>Reward / risk</td>
          <td className="num">{ratio(metrics.reward_risk)}</td>
        </tr>
      </tbody>
    </table>
  );
}

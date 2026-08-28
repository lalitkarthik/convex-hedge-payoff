"use client";

import {
  Area,
  ComposedChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { Curve } from "@/lib/types";
import { level, price } from "@/lib/format";

/**
 * **P&L at expiry** — not "payoff". `CONTEXT.md` is explicit that both lines a trader
 * sees are P&L; Payoff is the premium-blind terminal value, one subtraction away.
 *
 * **The x-axis is the Forward** (#72, `CONTEXT.md`) — the price the pricing model
 * actually consumes, and the unit every stored corner point is laid down in. It was
 * labelled "spot" while carrying exactly these numbers, which read as correct: the basis
 * is +118.87 at the anchor, so a Forward printed as a Spot is a plausible index level.
 *
 * 400 points across the Forward ±6%, with the region above zero and the region below it
 * visibly different. The colour change is a `linearGradient` whose offset sits exactly
 * where the curve crosses zero, which is why the fill switches at the axis rather than
 * at a rounded gridline.
 *
 * **Every colour here is a `var()`, and that is load-bearing.** Recharts takes colour
 * as JS props, so these values never touch the CSS cascade - and until the theme work
 * they were twelve hex literals hand-copied from `:root`, the one place in the app where
 * the palette was forked. A dark theme would have left the curve stroked near-black on a
 * near-black ground. Recharts forwards them to the SVG untouched: its only inspection of
 * `stroke` is `stroke !== 'none'`, an equality test, never a parse. The Tooltip is the
 * exception worth knowing about - its card defaults to white with dark text, set inline
 * by Recharts, so there was no literal here to find and `contentStyle` has to say so.
 *
 * Reference lines at the Forward and at every Breakeven. **The line never renders a
 * gap**: NaN cannot reach it — the wire type forbids one and the arithmetic upstream
 * cannot produce one — so a gap would mean a bug here rather than missing data.
 */
export default function PayoffChart({
  curve,
  forward,
  breakevens,
}: {
  curve: Curve;
  forward: number;
  breakevens: number[];
}) {
  // The wire carries two parallel arrays, as `models.Curve` publishes them and as the
  // prototype in #9 did; Recharts wants one array of records. Zipping is the whole of
  // the adaptation - the arrays are guaranteed the same length by a validator on the
  // model, so there is no ragged case to handle.
  const points = curve.forward.map((value, index) => ({
    forward: value,
    pnl: curve.pnl_at_expiry[index],
  }));
  const values = curve.pnl_at_expiry;
  const high = Math.max(...values, 0);
  const low = Math.min(...values, 0);

  // Where zero sits as a fraction of the vertical span. The gradient switches colour
  // exactly there, so "above water" and "below water" are the regions they claim to be.
  const zero = high === low ? 0.5 : high / (high - low);

  return (
    <div style={{ width: "100%", height: 260 }}>
      <ResponsiveContainer>
        <ComposedChart data={points} margin={{ top: 8, right: 8, bottom: 18, left: 4 }}>
          <defs>
            <linearGradient id="pnl" x1="0" y1="0" x2="0" y2="1">
              <stop offset={zero} stopColor="var(--gain)" stopOpacity={0.75} />
              <stop offset={zero} stopColor="var(--loss)" stopOpacity={0.75} />
            </linearGradient>
          </defs>

          <XAxis
            dataKey="forward"
            type="number"
            domain={["dataMin", "dataMax"]}
            tickFormatter={(value: number) => level(value)}
            tick={{ fontSize: 10, fill: "var(--ink-faint)" }}
            tickCount={6}
            // Titled, because an unlabelled axis of five-figure index levels reads as
            // Spot to anyone who has seen one of these charts before (#72).
            label={{
              value: "Forward at expiry",
              position: "insideBottom",
              offset: -12,
              fontSize: 10,
              fill: "var(--ink-faint)",
            }}
          />
          <YAxis
            tickFormatter={(value: number) => level(value)}
            tick={{ fontSize: 10, fill: "var(--ink-faint)" }}
            width={54}
          />

          <Tooltip
            labelFormatter={(value: number) => `Forward ${level(value)}`}
            formatter={(value: number) => [price(value), "P&L at expiry"]}
            contentStyle={{
              fontSize: 12,
              borderRadius: 6,
              border: "1px solid var(--line-strong)",
              // Recharts defaults the card to white with dark text, and does it inline,
              // so unlike the eleven above there was no literal here to find by grep.
              backgroundColor: "var(--surface)",
              color: "var(--ink)",
            }}
            itemStyle={{ color: "var(--ink)" }}
            labelStyle={{ color: "var(--ink-soft)" }}
          />

          <ReferenceLine y={0} stroke="var(--ink-soft)" strokeWidth={1} />
          <ReferenceLine
            x={forward}
            stroke="var(--accent)"
            strokeDasharray="4 3"
            label={{ value: "forward", position: "top", fontSize: 10, fill: "var(--accent)" }}
          />
          {breakevens.map((breakeven) => (
            <ReferenceLine
              key={breakeven}
              x={breakeven}
              stroke="var(--ink-faint)"
              strokeDasharray="2 3"
              label={{
                // Each Breakeven labelled with its distance from the Forward, because
                // "how far does it have to move" is the question being asked of this
                // chart — and the Forward is what the axis measures (#72).
                value: `${(((breakeven - forward) / forward) * 100).toFixed(1)}%`,
                position: "insideTopRight",
                fontSize: 9,
                fill: "var(--ink-soft)",
              }}
            />
          ))}

          <Area
            type="linear"
            dataKey="pnl"
            stroke="var(--ink)"
            strokeWidth={1.6}
            fill="url(#pnl)"
            isAnimationActive={false}
            dot={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

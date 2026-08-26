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

import type { CurvePoint } from "@/lib/skeleton-maths";
import { level, price } from "@/lib/format";

/**
 * **P&L at expiry** — not "payoff". `CONTEXT.md` is explicit that both lines a trader
 * sees are P&L; Payoff is the premium-blind terminal value, one subtraction away.
 *
 * 400 points across spot ±6%, with the region above zero and the region below it
 * visibly different. The colour change is a `linearGradient` whose offset sits exactly
 * where the curve crosses zero, which is why the fill switches at the axis rather than
 * at a rounded gridline.
 *
 * Reference lines at spot and at every Breakeven. **The line never renders a gap**: NaN
 * cannot reach it — the wire type forbids one and the arithmetic upstream cannot produce
 * one — so a gap would mean a bug here rather than missing data.
 */
export default function PayoffChart({
  curve,
  spot,
  breakevens,
}: {
  curve: CurvePoint[];
  spot: number;
  breakevens: number[];
}) {
  const values = curve.map((point) => point.pnl);
  const high = Math.max(...values, 0);
  const low = Math.min(...values, 0);

  // Where zero sits as a fraction of the vertical span. The gradient switches colour
  // exactly there, so "above water" and "below water" are the regions they claim to be.
  const zero = high === low ? 0.5 : high / (high - low);

  return (
    <div style={{ width: "100%", height: 260 }}>
      <ResponsiveContainer>
        <ComposedChart data={curve} margin={{ top: 8, right: 8, bottom: 4, left: 4 }}>
          <defs>
            <linearGradient id="pnl" x1="0" y1="0" x2="0" y2="1">
              <stop offset={zero} stopColor="#0f9d58" stopOpacity={0.75} />
              <stop offset={zero} stopColor="#d1383a" stopOpacity={0.75} />
            </linearGradient>
          </defs>

          <XAxis
            dataKey="spot"
            type="number"
            domain={["dataMin", "dataMax"]}
            tickFormatter={(value: number) => level(value)}
            tick={{ fontSize: 10, fill: "#93a0ac" }}
            tickCount={6}
          />
          <YAxis
            tickFormatter={(value: number) => level(value)}
            tick={{ fontSize: 10, fill: "#93a0ac" }}
            width={54}
          />

          <Tooltip
            labelFormatter={(value: number) => `Spot ${level(value)}`}
            formatter={(value: number) => [price(value), "P&L at expiry"]}
            contentStyle={{ fontSize: 12, borderRadius: 6, border: "1px solid #cdd3da" }}
          />

          <ReferenceLine y={0} stroke="#5b6773" strokeWidth={1} />
          <ReferenceLine
            x={spot}
            stroke="#4338ca"
            strokeDasharray="4 3"
            label={{ value: "spot", position: "top", fontSize: 10, fill: "#4338ca" }}
          />
          {breakevens.map((breakeven) => (
            <ReferenceLine
              key={breakeven}
              x={breakeven}
              stroke="#93a0ac"
              strokeDasharray="2 3"
              label={{
                // Each Breakeven labelled with its distance from spot, because "how far
                // does it have to move" is the question being asked of this chart.
                value: `${(((breakeven - spot) / spot) * 100).toFixed(1)}%`,
                position: "insideTopRight",
                fontSize: 9,
                fill: "#5b6773",
              }}
            />
          ))}

          <Area
            type="linear"
            dataKey="pnl"
            stroke="#16202b"
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

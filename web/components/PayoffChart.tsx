"use client";

import { useMemo, useState, type WheelEvent } from "react";
import {
  Area,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { Curve } from "@/lib/types";
import { level, price } from "@/lib/format";
import { split } from "@/lib/curve";
import { fit, fullSpan, zoom, type Span } from "@/lib/zoom";

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
 * visibly different. **Two Areas clamped either side of zero**, not one Area painted with
 * a gradient - see `lib/curve.ts` for why that was abandoned after three failed attempts
 * to place a gradient offset correctly. There is no offset now, and so nothing to place.
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
 *
 * ## Zoom
 *
 * ±6% is the right default and the wrong thing to be stuck with. A short straddle makes
 * 670 points across an x-axis three thousand points wide, so at full extent it is very
 * nearly a flat line - and its kink and both Breakevens live inside a fifth of the width.
 *
 * Wheel over the plot, or the buttons. **The vertical axis refits to whatever the window
 * contains**, which is the part that makes it useful: zooming without refitting shows the
 * same flat line, larger. `lib/zoom.ts` owns the rules and is tested without a browser.
 *
 * The window is deliberately *not* reset when the Strategy changes. A trader zoomed in on
 * a Breakeven is dragging a strike to watch that Breakeven move, and snapping back to
 * full extent on the first tick would undo the thing they zoomed in to see.
 */
export default function PayoffChart({
  curve,
  forward,
  breakevens,
  height = 420,
}: {
  curve: Curve;
  forward: number;
  breakevens: number[];
  height?: number;
}) {
  // The wire carries two parallel arrays, as `models.Curve` publishes them and as the
  // prototype in #9 did; Recharts wants one array of records. Zipping is the whole of
  // the adaptation - the arrays are guaranteed the same length by a validator on the
  // model, so there is no ragged case to handle.
  const points = useMemo(
    () =>
      curve.forward.map((value, index) => ({
        forward: value,
        pnl: curve.pnl_at_expiry[index]!,
      })),
    [curve],
  );

  const full = useMemo(() => fullSpan(curve.forward), [curve.forward]);

  // `null` is "the whole curve", and it is a distinct state from a window that happens to
  // equal the full extent: it survives the Strategy changing width underneath it, so a
  // chart that was never zoomed keeps following the data rather than freezing on the
  // extent it had when the first Leg was added.
  const [held, setHeld] = useState<Span | null>(null);
  const span = held ?? full;

  const vertical = useMemo(() => fit(points, span), [points, span]);

  // The two fills, and the crossings that make them meet on the axis. `split` is where
  // the colour rule lives; nothing here decides where green becomes red.
  const shaped = useMemo(() => split(points), [points]);

  const by = (factor: number, focus = (span.min + span.max) / 2) =>
    setHeld(zoom(full, span, factor, focus));

  function onWheel(event: WheelEvent<HTMLDivElement>) {
    // The Forward under the pointer, so the curve grows around the cursor. `currentTarget`
    // is the plot wrapper; the axis gutters are outside it, so this stays honest at the
    // edges without knowing Recharts' margins.
    const box = event.currentTarget.getBoundingClientRect();
    const at = (event.clientX - box.left) / box.width;
    by(event.deltaY < 0 ? 0.85 : 1 / 0.85, span.min + at * (span.max - span.min));
  }

  const zoomed = held !== null && span.max - span.min < full.max - full.min;

  return (
    <div className="chart">
      <div className="chart-tools">
        <span className="chart-range">
          {level(span.min)} – {level(span.max)}
        </span>
        <button className="step" onClick={() => by(1 / 0.7)} aria-label="zoom out">
          −
        </button>
        <button className="step" onClick={() => by(0.7)} aria-label="zoom in">
          +
        </button>
        <button
          className="step chart-reset"
          onClick={() => setHeld(null)}
          disabled={!zoomed}
          aria-label="reset zoom"
          title="Back to the whole curve"
        >
          ⤢
        </button>
      </div>

      {/* `onWheel` here rather than on the chart: Recharts owns its own SVG events, and
          the wrapper is also exactly the plot's width, which is what the focus maths
          needs. */}
      <div className="chart-plot" style={{ height }} onWheel={onWheel}>
      <ResponsiveContainer>
        <ComposedChart data={shaped} margin={{ top: 26, right: 12, bottom: 18, left: 4 }}>
          <XAxis
            dataKey="forward"
            type="number"
            domain={[span.min, span.max]}
            allowDataOverflow
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
            // Refitted to the window, which is the point of zooming at all - see the
            // docblock. `allowDataOverflow` lets the curve run past the frame rather than
            // being rescaled to fit, so the visible part keeps its true shape.
            domain={[vertical.min, vertical.max]}
            allowDataOverflow
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

          {/*
            Two fills and a separate stroke.

            Each Area is zero on the side it does not own, so the green one contributes
            nothing wherever the Strategy loses money and the red one contributes nothing
            wherever it makes any. The boundary is at zero because there is nowhere else
            it could be - which is the whole reason this is not a gradient any more.

            `tooltipType="none"` keeps them out of the hover card: they are one curve
            wearing two colours, and a tooltip listing three series would say otherwise.
          */}
          <Area
            type="linear"
            dataKey="gain"
            stroke="none"
            fill="var(--gain)"
            fillOpacity={0.75}
            isAnimationActive={false}
            dot={false}
            tooltipType="none"
            activeDot={false}
          />
          <Area
            type="linear"
            dataKey="loss"
            stroke="none"
            fill="var(--loss)"
            fillOpacity={0.75}
            isAnimationActive={false}
            dot={false}
            tooltipType="none"
            activeDot={false}
          />
          <Line
            type="linear"
            dataKey="pnl"
            stroke="var(--ink)"
            strokeWidth={1.6}
            isAnimationActive={false}
            dot={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
      </div>
    </div>
  );
}

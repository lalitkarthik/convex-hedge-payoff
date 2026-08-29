/**
 * The P&L curve, split into the part above water and the part below it.
 *
 * ## Why this exists instead of a gradient
 *
 * The two regions used to be one filled `Area` painted with a two-stop `linearGradient`
 * whose offset sat where the curve crossed zero. That offset is a fraction of the
 * **filled shape's bounding box**, because SVG gradients default to `objectBoundingBox`
 * units - and the bounding box is the browser's idea of the path's extent, which is not
 * something this component can see. It moved when padding was added to the vertical
 * domain, it moved again when the axis refitted under zoom, and the reference had to be
 * re-keyed by hand to force a repaint when the offset changed. Each fix was arithmetically
 * defensible and the band of miscoloured profit above the axis survived all of them.
 *
 * So the geometry is no longer inferred. Two Areas, each clamped to one side of zero and
 * both baselined there, put the colour change exactly at zero because there is nothing
 * left to compute: the green series is zero everywhere the Strategy loses money, and the
 * red one is zero everywhere it makes any.
 *
 * The one thing it needs is **exact crossing points**. The curve is sampled at 400 evenly
 * spaced Forwards, so a crossing almost never lands on a sample; clamping without one
 * leaves the fill to start at the first sample past zero, which is a visible notch at
 * every Breakeven. Interpolating the crossing costs one point per crossing and makes the
 * two fills meet on the axis exactly.
 */

export interface Point {
  forward: number;
  pnl: number;
}

/** One sample, split across the two series. Zero in both where the curve is at zero. */
export interface Split extends Point {
  gain: number;
  loss: number;
}

/**
 * The curve with its zero crossings made explicit, then clamped into two series.
 *
 * A crossing is inserted only between samples that genuinely straddle zero - `a * b < 0`
 * is false when either endpoint *is* zero, so a sample already sitting on the axis is
 * used as the crossing rather than duplicated beside one.
 */
export function split(points: Point[]): Split[] {
  const out: Split[] = [];

  for (let i = 0; i < points.length; i++) {
    const point = points[i]!;
    out.push({ ...point, gain: Math.max(point.pnl, 0), loss: Math.min(point.pnl, 0) });

    const next = points[i + 1];
    if (next === undefined) continue;
    if (point.pnl * next.pnl >= 0) continue;

    // Linear between the two samples, which is also how the chart draws between them -
    // so the inserted point sits on the line rather than near it.
    const at = (0 - point.pnl) / (next.pnl - point.pnl);
    out.push({
      forward: point.forward + (next.forward - point.forward) * at,
      pnl: 0,
      gain: 0,
      loss: 0,
    });
  }

  return out;
}

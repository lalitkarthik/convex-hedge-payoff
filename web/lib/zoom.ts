/**
 * The window the payoff chart looks through, and how it moves.
 *
 * All of it pure. The chart owns *which* window is current; these functions own what a
 * window is allowed to be, and those are the rules worth asserting without a browser.
 *
 * Two of them carry the file. **The window never leaves the data**: the curve is 400
 * points across the Forward ±6% and there is nothing outside that to draw, so a window
 * that escaped would render as empty axis and read as a broken chart rather than as the
 * end of the data. And **the focus point stays put**, which is the whole difference
 * between zooming and scrolling - the strike under the pointer must still be under the
 * pointer afterwards, or the curve appears to slide away as it grows.
 */

export interface Span {
  min: number;
  max: number;
}

/**
 * The narrowest the window may get, as a fraction of the full extent.
 *
 * 400 points span the full width, so 5% is twenty of them - enough that the curve still
 * reads as a curve. Below that the kink at a strike starts to look like a straight line
 * seen very close up, which is a worse picture rather than a more detailed one.
 */
export const MIN_FRACTION = 0.05;

/** The extent of the curve, and `0..0` rather than `Infinity..-Infinity` when empty. */
export function fullSpan(forwards: number[]): Span {
  if (forwards.length === 0) return { min: 0, max: 0 };
  return { min: Math.min(...forwards), max: Math.max(...forwards) };
}

/**
 * Zoom about a focus point. Below 1 narrows, above 1 widens.
 *
 * The focus keeps its relative position across the change, then the result is slid back
 * inside the full extent if it would overhang. Those two rules disagree at the very edges
 * - zooming on the last point cannot keep it at the far right and also show data to its
 * right - and staying inside the data wins, because the alternative is blank axis.
 */
export function zoom(full: Span, current: Span, factor: number, focus: number): Span {
  const fullWidth = full.max - full.min;
  if (fullWidth <= 0) return full;

  const width = current.max - current.min;
  const next = Math.min(fullWidth, Math.max(fullWidth * MIN_FRACTION, width * factor));

  // Where the focus sits across the current window, kept across the resize.
  const at = width > 0 ? (focus - current.min) / width : 0.5;
  let min = focus - at * next;

  // Slid, not clamped independently: adjusting one edge alone would change the width and
  // undo the zoom that was just applied.
  if (min < full.min) min = full.min;
  if (min + next > full.max) min = full.max - next;

  return { min, max: min + next };
}

/**
 * The vertical extent of whatever the window contains, with a little air.
 *
 * This is the reason zoom is worth having at all. A short straddle makes 670 points
 * across an x-axis 3,000 points wide, so at full extent it is very nearly a flat line;
 * zooming in without refitting the vertical axis shows the same flat line, larger.
 *
 * Zero is not forced into the span. Keeping it would be defensible - it is where the
 * `ReferenceLine` sits - but it also means a window entirely above water still has to
 * reach down to zero, and that is the case where a trader has zoomed in precisely
 * because they want to see the shape of the profit.
 */
export function fit(points: { forward: number; pnl: number }[], span: Span): Span {
  const inside = points.filter((p) => p.forward >= span.min && p.forward <= span.max);
  // Reachable by holding a zoomed window while the Strategy changes underneath it. An
  // inverted or empty domain makes Recharts draw through the frame, so fall back wide.
  const values = (inside.length > 0 ? inside : points).map((p) => p.pnl);
  if (values.length === 0) return { min: -1, max: 1 };

  const low = Math.min(...values);
  const high = Math.max(...values);
  // A flat curve has no height to take a percentage of, so the pad has a floor.
  const pad = Math.max((high - low) * 0.08, 1);

  return { min: low - pad, max: high + pad };
}

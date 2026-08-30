import { describe, expect, test } from "bun:test";

import { contain, fit, fullSpan, wheelFactor, zoom, MIN_FRACTION } from "./zoom";

/**
 * The window the payoff chart is looking through.
 *
 * The curve is 400 points across the Forward ±6%, which is the right default and the
 * wrong thing to be stuck with: the interesting part of a Strategy is usually a few
 * hundred points wide, and at full extent a straddle's kink and both Breakevens sit
 * inside a fifth of the width.
 *
 * Two rules carry this file. **The window never leaves the data** - there is nothing
 * outside ±6% to draw, so a window that escaped it would show empty axis and read as a
 * broken chart. And **the focus point stays put**, which is what makes wheel zoom feel
 * like zooming rather than like scrolling: the strike under the pointer is the strike
 * still under the pointer afterwards.
 */

const FULL = { min: 23700, max: 26700 };

describe("fullSpan", () => {
  test("is the extent of the curve", () => {
    expect(fullSpan([25000, 23700, 26700, 25200])).toEqual({ min: 23700, max: 26700 });
  });

  test("an empty curve is a zero span rather than Infinity", () => {
    // `Math.min()` of nothing is Infinity, which would reach the axis domain and render
    // as an empty chart with no error anywhere.
    expect(fullSpan([])).toEqual({ min: 0, max: 0 });
  });
});

describe("zoom", () => {
  test("narrows about the focus, keeping it where it was", () => {
    // Focus dead centre, halve the width: the centre is still the centre.
    const next = zoom(FULL, FULL, 0.5, 25200);

    expect(next.max - next.min).toBeCloseTo(1500, 6);
    expect((25200 - next.min) / (next.max - next.min)).toBeCloseTo(0.5, 6);
  });

  test("an off-centre focus keeps its own relative position", () => {
    // The wheel-zoom property. The pointer is a quarter of the way across; after the
    // zoom the same Forward is still a quarter of the way across, so the curve appears
    // to grow around the cursor rather than slide under it.
    const focus = FULL.min + (FULL.max - FULL.min) * 0.25;
    const next = zoom(FULL, FULL, 0.5, focus);

    expect((focus - next.min) / (next.max - next.min)).toBeCloseTo(0.25, 6);
  });

  test("never opens wider than the data", () => {
    // There is nothing outside ±6% to draw. A window wider than the curve is empty axis.
    expect(zoom(FULL, FULL, 4, 25200)).toEqual(FULL);
  });

  test("zooming out from close in lands back on the full extent, not past it", () => {
    const close = zoom(FULL, FULL, 0.25, 25200);
    expect(zoom(FULL, close, 100, 25200)).toEqual(FULL);
  });

  test("stops narrowing at a floor, so the curve cannot be zoomed into nothing", () => {
    const tiny = zoom(FULL, FULL, 0.0001, 25200);
    const width = (FULL.max - FULL.min) * MIN_FRACTION;

    expect(tiny.max - tiny.min).toBeCloseTo(width, 6);
  });

  test("a window that would run off the end is shifted back inside", () => {
    // Zooming on the far right edge. The focus cannot stay put here - there is no data
    // to its right - so the window slides rather than escaping, which is the one case
    // where holding the focus and staying inside the data disagree.
    const next = zoom(FULL, FULL, 0.5, FULL.max);

    expect(next.max).toBe(FULL.max);
    expect(next.min).toBeCloseTo(FULL.max - 1500, 6);
  });
});

describe("fit", () => {
  const POINTS = [
    { forward: 24000, pnl: -500 },
    { forward: 25000, pnl: 100 },
    { forward: 25200, pnl: 300 },
    { forward: 26000, pnl: -200 },
  ];

  test("fits the vertical axis to what is actually visible", () => {
    // The reason zoom is worth having. At full extent a 670-point straddle is a flat
    // line against a 25,000-point x-axis; zoomed in, the axis has to follow or the
    // zoom shows the same flat line larger.
    const span = fit(POINTS, { min: 24900, max: 25300 });

    expect(span.min).toBeLessThan(100);
    expect(span.max).toBeGreaterThan(300);
    // -500 is outside the window and must not be setting the floor.
    expect(span.min).toBeGreaterThan(-500);
  });

  test("pads, so the curve does not touch the frame", () => {
    const span = fit(POINTS, { min: 24900, max: 25300 });
    expect(span.min).toBeLessThan(100);
    expect(span.max).toBeGreaterThan(300);
  });

  test("a window containing nothing falls back rather than inverting", () => {
    // Reachable while a zoomed window is held and the Strategy changes under it.
    const span = fit(POINTS, { min: 1, max: 2 });
    expect(span.min).toBeLessThan(span.max);
  });

  test("a flat curve still gets a span with height", () => {
    // A zero-width vertical domain makes Recharts draw the line through the frame edge.
    const flat = [{ forward: 25000, pnl: 0 }, { forward: 25200, pnl: 0 }];
    const span = fit(flat, { min: 24000, max: 26000 });

    expect(span.max).toBeGreaterThan(span.min);
  });
});

describe("fit keeps zero", () => {
  const PROFIT = [
    { forward: 25000, pnl: 400 },
    { forward: 25200, pnl: 670 },
  ];

  test("a window entirely in profit still reaches down to zero", () => {
    // Not cosmetic. A Recharts `Area` draws from the curve to its baseline, and the
    // baseline is zero only while zero is inside the domain - outside it, it clamps to
    // the nearest edge, which changes the filled shape. `waterline` measures against
    // that shape, so a domain without zero paints the boundary against a box that does
    // not exist, and the fill comes out the wrong colour.
    expect(fit(PROFIT, { min: 24900, max: 25300 }).min).toBeLessThanOrEqual(0);
  });

  test("a window entirely under water still reaches up to zero", () => {
    const loss = PROFIT.map((p) => ({ ...p, pnl: -p.pnl }));
    expect(fit(loss, { min: 24900, max: 25300 }).max).toBeGreaterThanOrEqual(0);
  });
});

describe("contain", () => {
  // Reachable only since the engine started sizing the window to the Strategy: `full`
  // used to be a constant +/-6%, so a held window was inside it by construction. Now a
  // window held on an iron butterfly whose wings reach 27,438 survives the removal of
  // both wings, and the data behind it stops at 26,732.
  test("slides a held window back inside a full extent that shrank underneath it", () => {
    const full = { min: 23706, max: 26732 };
    const held = { min: 26900, max: 27438 };

    const inside = contain(full, held);

    expect(inside.max).toBeLessThanOrEqual(full.max);
    expect(inside.min).toBeGreaterThanOrEqual(full.min);
    // Slid, not truncated: the trader's zoom level is what they chose, and shrinking it
    // as well would zoom them out by an amount they never asked for.
    expect(inside.max - inside.min).toBeCloseTo(held.max - held.min, 6);
  });

  test("gives back a window that already fits, unchanged", () => {
    const full = { min: 23000, max: 27000 };
    const held = { min: 25000, max: 25500 };

    expect(contain(full, held)).toEqual(held);
  });

  test("cannot return a window wider than the data", () => {
    const full = { min: 24000, max: 25000 };

    expect(contain(full, { min: 20000, max: 30000 })).toEqual(full);
  });
});

describe("wheelFactor", () => {
  test("narrows the window when the wheel turns towards the screen", () => {
    expect(wheelFactor(-100)).toBeLessThan(1);
    expect(wheelFactor(100)).toBeGreaterThan(1);
  });

  test("keeps a notch of the wheel worth about the 15% it always was", () => {
    // A mouse wheel reports around 100 per notch. This is the number that was hard-coded
    // before pinch made it have to vary, and it is a comfortable step.
    expect(wheelFactor(-100)).toBeCloseTo(0.85, 2);
    expect(wheelFactor(100)).toBeCloseTo(1 / 0.85, 1);
  });

  test("is continuous, so a pinch's many small deltas do not lurch", () => {
    // A trackpad pinch fires a stream of events with deltas in the single digits. A fixed
    // step per event would zoom by 0.85^30 across one gesture, which is 100x.
    expect(wheelFactor(-4)).toBeGreaterThan(0.98);
    expect(wheelFactor(-4)).toBeLessThan(1);

    // Ten small ones compose to about one big one, which is what "continuous" has to mean
    // for a gesture that can be delivered either way.
    const ten = Array.from({ length: 10 }, () => wheelFactor(-10)).reduce((a, b) => a * b, 1);
    expect(ten).toBeCloseTo(wheelFactor(-100), 6);
  });

  test("caps a single event, because some devices send one enormous delta", () => {
    // Chrome reports deltaMode 0 in pixels, but a page-mode wheel or a coarse driver can
    // deliver several thousand at once, and one event should not cross the whole range.
    expect(wheelFactor(-100000)).toBeGreaterThanOrEqual(0.25);
    expect(wheelFactor(100000)).toBeLessThanOrEqual(4);
  });
});

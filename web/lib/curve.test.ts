import { describe, expect, test } from "bun:test";

import { split } from "./curve";

/**
 * Splitting the curve at zero, which is what colours the chart.
 *
 * This replaced a gradient whose colour boundary was a fraction of the filled shape's
 * bounding box. That fraction was correct on paper three times running and wrong on
 * screen every time, because the bounding box is the browser's and moved with padding,
 * with zoom, and with a repaint that did not happen. Here there is no fraction: the green
 * series is zero wherever the Strategy loses and the red one is zero wherever it gains,
 * so the two fills meet at zero because they cannot meet anywhere else.
 */

describe("split", () => {
  test("profit goes to gain and leaves loss at zero", () => {
    const [only] = split([{ forward: 25000, pnl: 300 }]);
    expect(only).toEqual({ forward: 25000, pnl: 300, gain: 300, loss: 0 });
  });

  test("a loss goes to loss and leaves gain at zero", () => {
    const [only] = split([{ forward: 25000, pnl: -300 }]);
    expect(only).toEqual({ forward: 25000, pnl: -300, gain: 0, loss: -300 });
  });

  test("a crossing is inserted exactly where the line meets the axis", () => {
    // Samples 200 apart, P&L going +100 to -100, so the crossing is the midpoint. The
    // curve is drawn linearly between samples, so this point sits on the line rather
    // than merely near it.
    const out = split([
      { forward: 25000, pnl: 100 },
      { forward: 25200, pnl: -100 },
    ]);

    expect(out).toHaveLength(3);
    expect(out[1]).toEqual({ forward: 25100, pnl: 0, gain: 0, loss: 0 });
  });

  test("an off-centre crossing is interpolated, not rounded to a sample", () => {
    // Without this the fill starts at the first sample past zero. At 400 samples across
    // 3,000 points of Forward that is a 7.5-point notch at every Breakeven.
    const out = split([
      { forward: 25000, pnl: 30 },
      { forward: 25100, pnl: -70 },
    ]);

    expect(out[1]!.forward).toBeCloseTo(25030, 6);
    expect(out[1]!.pnl).toBe(0);
  });

  test("both Breakevens of a straddle get one", () => {
    // A short straddle crosses twice. Missing either leaves one Breakeven notched and
    // the other clean, which reads as a rendering glitch rather than a bug.
    const out = split([
      { forward: 24000, pnl: -400 },
      { forward: 25000, pnl: 400 },
      { forward: 26000, pnl: -400 },
    ]);

    expect(out.filter((p) => p.pnl === 0)).toHaveLength(2);
    expect(out).toHaveLength(5);
  });

  test("a sample already on the axis is used, not duplicated", () => {
    // `a * b < 0` is false when either endpoint is zero, so the existing point is the
    // crossing. Inserting beside it would put two points at the same Forward and give
    // the fill a zero-width segment to draw.
    const out = split([
      { forward: 25000, pnl: 100 },
      { forward: 25100, pnl: 0 },
      { forward: 25200, pnl: -100 },
    ]);

    expect(out).toHaveLength(3);
    expect(out[1]).toEqual({ forward: 25100, pnl: 0, gain: 0, loss: 0 });
  });

  test("a curve that never crosses gains no points", () => {
    const out = split([
      { forward: 25000, pnl: 100 },
      { forward: 25100, pnl: 200 },
    ]);
    expect(out).toHaveLength(2);
  });

  test("order is preserved, because the axis is drawn in it", () => {
    const out = split([
      { forward: 24000, pnl: -400 },
      { forward: 25000, pnl: 400 },
      { forward: 26000, pnl: -400 },
    ]);
    const forwards = out.map((p) => p.forward);

    expect(forwards).toEqual([...forwards].sort((a, b) => a - b));
  });

  test("an empty curve is empty rather than a throw", () => {
    expect(split([])).toEqual([]);
  });
});

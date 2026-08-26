/**
 * ⚠ THROWAWAY. Delete this file the day `POST /analyse` is wired.
 *
 * This is a **second implementation** of `src/payoff/strategy.py`, which is exactly the
 * duplication ADR-0001 and the golden test exist to prevent. It is here only because the
 * skeleton has no server to ask, and it is confined to this one file so that deleting it
 * is a deletion rather than an excavation. **If this maths spreads to a component, the
 * containment has failed.**
 *
 * The line it does not cross: **arithmetic yes, model no.**
 *
 *   - P&L at expiry is `max(S − K, 0)` minus a premium. Arithmetic. No assumptions in
 *     it, nothing to get subtly wrong, and it agrees with the engine exactly.
 *   - Black-76 is a **model**. A copy of it here would be a second answer to the same
 *     question, and the two would diverge silently. So the Greeks are not computed —
 *     they are per-contract values from the fixture, multiplied by direction and
 *     quantity, which is arithmetic too.
 *
 * Every function mirrors its `strategy.py` counterpart, deliberately including the
 * awkward parts: extrema are read off the **kinks** rather than a sampled grid, because
 * a scan steps past a peak that sits exactly on a strike and reports 670.703 where the
 * answer is 670.75.
 */

import type { Greeks, Leg, Metrics } from "./types";

export const CURVE_POINTS = 400;
export const SPOT_RANGE = 0.06;

/** Premium-blind terminal value — **Payoff** in CONTEXT.md's sense, not P&L. */
export function intrinsicValue(spot: number, strike: number, isCall: boolean): number {
  return isCall ? Math.max(spot - strike, 0) : Math.max(strike - spot, 0);
}

/** P&L at expiry: signed by direction, scaled by quantity, no branching on leg count. */
export function pnlAtExpiry(spot: number, legs: Leg[]): number {
  return legs.reduce((total, leg) => {
    const value = intrinsicValue(spot, leg.strike, leg.optionType === "CE");
    return total + leg.direction * leg.quantity * (value - leg.entryPremium);
  }, 0);
}

/** Positive is paid out (a debit); negative is received (a credit) — CONTEXT.md. */
export function netPremium(legs: Leg[]): number {
  return legs.reduce((sum, leg) => sum + leg.direction * leg.quantity * leg.entryPremium, 0);
}

export interface CurvePoint {
  spot: number;
  pnl: number;
}

export function curve(legs: Leg[], spotCentre: number): CurvePoint[] {
  const low = spotCentre * (1 - SPOT_RANGE);
  const high = spotCentre * (1 + SPOT_RANGE);
  const step = (high - low) / (CURVE_POINTS - 1);
  return Array.from({ length: CURVE_POINTS }, (_, i) => {
    const spot = low + i * step;
    return { spot, pnl: pnlAtExpiry(spot, legs) };
  });
}

/**
 * The spots where the expiry payoff changes slope, plus both tails.
 *
 * P&L at expiry is piecewise linear and bends only at a strike, so these points describe
 * the whole curve exactly. The left edge is 0 because **spot cannot fall below zero** —
 * which is also why only the right-hand tail can ever be Unbounded.
 */
function kinks(legs: Leg[]): number[] {
  const strikes = [...new Set(legs.map((leg) => leg.strike))].sort((a, b) => a - b);
  return [0, ...strikes, strikes[strikes.length - 1] * 2];
}

/** Solved between adjacent kinks rather than searched for, so they are exact. */
export function breakevens(legs: Leg[]): number[] {
  const points = kinks(legs);
  const pnl = points.map((spot) => pnlAtExpiry(spot, legs));

  const found = points.filter((_, i) => pnl[i] === 0);
  for (let i = 0; i < points.length - 1; i += 1) {
    const [before, after] = [pnl[i], pnl[i + 1]];
    if (Math.sign(before) * Math.sign(after) < 0) {
      const [left, right] = [points[i], points[i + 1]];
      found.push(left - (before * (right - left)) / (after - before));
    }
  }
  return [...new Set(found.map((value) => Math.round(value * 1e6) / 1e6))].sort((a, b) => a - b);
}

/**
 * Does the far tail keep running? Decided from the net signed quantity of calls, which
 * governs the slope far above every strike — no leg-count branching and no need to
 * recognise the shape by name.
 */
function isUnbounded(legs: Leg[], upside: boolean): boolean {
  const callSlope = legs
    .filter((leg) => leg.optionType === "CE")
    .reduce((sum, leg) => sum + leg.direction * leg.quantity, 0);
  return upside ? callSlope > 0 : callSlope < 0;
}

export function metrics(legs: Leg[]): Metrics {
  const pnl = kinks(legs).map((spot) => pnlAtExpiry(spot, legs));

  const maxProfit = isUnbounded(legs, true) ? null : Math.max(...pnl);
  const maxLoss = isUnbounded(legs, false) ? null : Math.min(...pnl);

  // A ratio against an Unbounded gain has no meaning, and a large number in its place
  // would read as a good trade.
  const rewardRisk =
    maxProfit !== null && maxLoss !== null && maxLoss < 0 ? maxProfit / Math.abs(maxLoss) : null;

  return { maxProfit, maxLoss, breakevens: breakevens(legs), netPremium: netPremium(legs), rewardRisk };
}

/**
 * `G = Σ dᵢ qᵢ gᵢ` — **multiplication, not pricing.**
 *
 * The per-contract Greeks come from the fixture's `contract_greeks`, which the engine
 * computed. Nothing here evaluates Black-76, which is the whole point: the aggregation
 * is the only part a client is allowed to do.
 */
export function legGreeks(legs: Leg[], perContract: Record<string, Greeks>): (Greeks | null)[] {
  return legs.map((leg) => {
    const source = perContract[`${leg.strike.toFixed(0)}${leg.optionType}`];
    if (!source) return null;
    const scale = leg.direction * leg.quantity;
    return {
      delta: scale * source.delta,
      gamma: scale * source.gamma,
      vega: scale * source.vega,
      theta: scale * source.theta,
      rho: scale * source.rho,
    };
  });
}

export function totalGreeks(rows: (Greeks | null)[]): Greeks | null {
  const present = rows.filter((row): row is Greeks => row !== null);
  if (present.length === 0) return null;
  const sum = (name: keyof Greeks) => present.reduce((running, row) => running + row[name], 0);
  return {
    delta: sum("delta"),
    gamma: sum("gamma"),
    vega: sum("vega"),
    theta: sum("theta"),
    rho: sum("rho"),
  };
}

/** The Payoff Table: P&L at 50-point intervals, the grid this chain actually trades on. */
export function payoffTable(legs: Leg[], spotCentre: number, step = 50): CurvePoint[] {
  const low = Math.ceil((spotCentre * (1 - SPOT_RANGE)) / step) * step;
  const high = Math.floor((spotCentre * (1 + SPOT_RANGE)) / step) * step;
  const rows: CurvePoint[] = [];
  for (let spot = low; spot <= high; spot += step) {
    rows.push({ spot, pnl: pnlAtExpiry(spot, legs) });
  }
  return rows;
}

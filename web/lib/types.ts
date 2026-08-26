/**
 * The wire types, mirroring `src/payoff/models.py` by hand.
 *
 * By hand **only for the skeleton**. The backend publishes `/openapi.json`, generated
 * from those same pydantic models, and the moment there is a server to read it from
 * these are generated instead — so a response shape change breaks the build rather than
 * producing an `undefined` in front of a trader.
 *
 * Two conventions here surprise people and are worth stating where they are read:
 *
 *  - `maxProfit` / `maxLoss` are `number | null`, and `null` means **Unlimited**. Never
 *    an infinity token, never a string, never blank.
 *  - `delta` and `gamma` are **discounted** (#53), so a call's delta is bounded by the
 *    discount factor rather than by 1.
 */

export type OptionType = "CE" | "PE";
export type Direction = 1 | -1;
export type ForwardMethod = "parity_fit" | "single_strike_parity" | "spot";

export interface ChainQuote {
  last: number;
  open_interest: number;
  volume: number;
  /** How stale this print is. Reaches 153 at the wings, so it has to be visible. */
  age_minutes: number;
  delta: number;
}

export interface ChainRow {
  strike: number;
  /** One value per strike, never one per side — it is a property of the strike (#28). */
  iv: number | null;
  call: ChainQuote | null;
  put: ChainQuote | null;
}

export interface Greeks {
  delta: number;
  gamma: number;
  vega: number;
  theta: number;
  rho: number;
}

export interface ChainResponse {
  moment: string;
  spot: number;
  expiry: string;
  forward: number;
  discount: number;
  forward_method: ForwardMethod;
  rows: ChainRow[];
  /**
   * **Fixture-only.** The real `ChainQuote` publishes `delta` alone; the other four
   * reach a client through `POST /analyse`, which the skeleton has no server to call.
   * Keyed `25200CE`. This field goes the day the backend is wired.
   */
  contract_greeks: Record<string, Greeks>;
}

export interface Session {
  first_moment: string;
  last_moment: string;
  /** File stems, `2026-01-27T06-30-00`, in session order. 376 of them. */
  moments: string[];
  moment_count: number;
  expiry: string;
  strike_min: number;
  strike_max: number;
  presets: string[];
}

/** A Leg as a client may describe it. No volatility: the server looks that up. */
export interface LegRequest {
  strike: number;
  option_type: OptionType;
  direction: Direction;
  quantity?: number;
  entry_premium?: number | null;
}

/** A Leg once the client has chosen it. Entry Premium and iv come off the Chain. */
export interface Leg {
  strike: number;
  optionType: OptionType;
  direction: Direction;
  quantity: number;
  entryPremium: number;
  iv: number | null;
}

/** `null` on either bound means **Unlimited**, and is rendered as that word. */
export interface Metrics {
  maxProfit: number | null;
  maxLoss: number | null;
  breakevens: number[];
  netPremium: number;
  rewardRisk: number | null;
}

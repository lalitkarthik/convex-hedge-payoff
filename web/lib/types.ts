/**
 * The wire types — **the shapes `src/payoff/models.py` publishes**, spelled as they
 * arrive.
 *
 * Two things changed here when the backend was wired, and both were deletions:
 *
 *  - The **camelCase mirror** is gone. There used to be a `Metrics` with `maxProfit` and
 *    a `Leg` with `entryPremium`, adapted at the boundary from the `max_profit` and
 *    `entry_premium` the server actually sends. One vocabulary now, and it is the
 *    server's — so a field can be traced from `models.py` to the cell it renders in
 *    without a rename in the middle.
 *  - `contract_greeks` is gone. It was a fixture artefact carrying all five Greeks per
 *    strike per side, and it existed only so the skeleton's Greeks tab could work with
 *    no server to ask. `/analyse` returns them now.
 *
 * These are checked against the schema, not merely believed: `web/openapi.json` is
 * generated from the same pydantic models, and `tests/test_openapi_contract.py` fails if
 * it drifts from the app. Run `python scripts/dump_openapi.py` after any change to the
 * seam.
 *
 * Two conventions surprise people and are worth stating where they are read:
 *
 *  - `max_profit` / `max_loss` are `number | null`, and **`null` means Unlimited**.
 *    Never an infinity token, never a string, never blank (CONTEXT.md).
 *  - `delta` and `gamma` are **discounted** (#53), so a call's delta is bounded by the
 *    discount factor rather than by 1.
 */

export type OptionType = "CE" | "PE";
export type Direction = 1 | -1;
export type ForwardMethod = "parity_fit" | "single_strike_parity" | "spot";

/** The day. Asked once, before anything else can name a moment. */
export interface SessionResponse {
  /** Every minute that quoted, ISO 8601, in session order. 376 of them. */
  moments: string[];
  moment_count: number;
  first_moment: string;
  last_moment: string;
  expiry: string;
  strike_min: number;
  strike_max: number;
  presets: string[];
}

export interface ChainQuote {
  last: number;
  open_interest: number;
  volume: number;
  /** How stale this print is. Reaches 153 at the wings, so it has to be visible. */
  age_minutes: number;
  /** Per side, and genuinely so: a call and its put have deltas one apart, not equal. */
  delta: number;
}

export interface ChainRow {
  strike: number;
  /** One value per strike, never one per side — it is a property of the strike (#28). */
  iv: number | null;
  call: ChainQuote | null;
  put: ChainQuote | null;
}

export interface ChainResponse {
  moment: string;
  spot: number;
  expiry: string;
  /** Fitted from the quotes by put-call parity (#51), never read from the file. */
  forward: number;
  discount: number;
  /** Which tier of the ladder answered. On 60 of 376 minutes it is assumed, not measured. */
  forward_method: ForwardMethod;
  rows: ChainRow[];
}

/** A Leg as a client may describe it. No volatility: the server looks that up. */
export interface LegRequest {
  strike: number;
  option_type: OptionType;
  direction: Direction;
  quantity?: number;
  /** Absent means "use the Chain's last traded price". Never send 0 to mean absent. */
  entry_premium?: number | null;
}

export interface AnalysisRequest {
  moment: string;
  legs: LegRequest[];
}

/** Two parallel arrays, as a chart consumes them. Both lines are P&L, not Payoff. */
export interface Curve {
  spot: number[];
  pnl_at_expiry: number[];
}

/** `null` on either bound means **Unlimited**, and is rendered as that word. */
export interface Metrics {
  max_profit: number | null;
  max_loss: number | null;
  breakevens: number[];
  net_premium: number;
  reward_risk: number | null;
}

/** Per contract: no Lot Size, no lot count. Those are presentation multipliers (#29). */
export interface LegGreeks {
  delta: number;
  gamma: number;
  vega: number;
  theta: number;
  rho: number;
}

/** Everything about one Strategy, in one response. Deliberately fat (#23). */
export interface AnalysisResponse {
  moment: string;
  spot: number;
  forward: number;
  discount: number;
  curve: Curve;
  metrics: Metrics;
  /** The same P&L on the 50-point grid a trader reads (#29). */
  table: Curve;
  /** One row per Leg, in the order they were sent — read beside them on screen (#27). */
  greeks: LegGreeks[];
  /** `G = Σ dᵢqᵢgᵢ`. `null` only when there are no Legs to sum. */
  total_greeks: LegGreeks | null;
}

export interface PresetResponse {
  presets: string[];
  legs?: LegRequest[];
}

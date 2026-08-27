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
 *  - `delta` and `gamma` are **undiscounted**, so a call's delta is bounded by 1 and a
 *    call's delta less its put's is exactly 1 at every strike. `vega` and `rho` do carry
 *    the discount factor.
 */

export type OptionType = "CE" | "PE";
export type Direction = 1 | -1;
export type ForwardMethod = "parity_fit" | "single_strike_parity" | "spot";

/**
 * One day and one Expiry. Asked whenever either dropdown moves.
 *
 * `date` and `expiry` name the pair this response describes, and they are **not
 * necessarily the pair that was asked for** (#68): a request naming a date and an Expiry
 * that date did not trade is resolved to a pair the store holds rather than refused. So
 * a client renders these two fields, not what it sent — which is what keeps changing the
 * date from producing an empty Chain.
 */
export interface SessionResponse {
  /** The trading date this session describes, ISO 8601. */
  date: string;
  /** Every trading date in the store, ascending. What the date dropdown lists. */
  dates: string[];
  /** Every minute that quoted, ISO 8601, in session order. 376 of them on the anchor. */
  moments: string[];
  moment_count: number;
  first_moment: string;
  last_moment: string;
  /** The Expiry this session describes, spelled as `ChainResponse.expiry` spells it. */
  expiry: string;
  /**
   * Every Expiry that traded on `date`, ascending. What the Expiry dropdown lists — only
   * the ones that traded *that day*, so a pair the store does not hold is unpickable.
   */
  expiries: string[];
  strike_min: number;
  strike_max: number;
  presets: string[];
}

/**
 * The header at one minute — and nothing about any strike (#69).
 *
 * Spot, the Forward, the Discount Factor and the at-the-money volatility belong to the
 * **minute**. In the stored Chain they repeat across every one of that minute's ~196
 * rows, so a header that read them there opened the largest artifact in the tree to take
 * four numbers out of it. They are stored once instead, one row a minute, and this is
 * that row.
 *
 * Dragging the time control moves the header 375 times across a session. Every one of
 * those was a read of the Chain and is now a lookup.
 *
 * Every figure here is the one `ChainResponse` publishes for the same minute — by
 * construction, because the build reduces the Chain frame it is about to write.
 */
export interface SummaryResponse {
  moment: string;
  /** The pair this row belongs to, spelled as `/session` and `/chain` spell them. */
  date: string;
  expiry: string;
  spot: number;
  forward: number;
  discount: number;
  forward_method: ForwardMethod;
  /** Nearest quoted strike to the **Forward**, not to Spot — the basis reaches +118.87. */
  atm_strike: number;
  /**
   * That strike's implied volatility, by the same rule `ChainRow.iv` follows. Null where
   * the print no volatility reproduces — every strike in the last minute of Expiry day.
   */
  atm_iv: number | null;
}

export interface ChainQuote {
  last: number;
  open_interest: number;
  volume: number;
  /** How stale this print is. Reaches 153 at the wings, so it has to be visible. */
  age_minutes: number;
  /**
   * Per side, and genuinely so: a call and its put have deltas one apart, not equal.
   * Null together with the row's `iv`: a delta is priced at the strike's volatility, so
   * a print no volatility reproduces has no delta to publish either.
   */
  delta: number | null;
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

/**
 * A Leg as a client may describe it. No volatility: the server looks that up.
 *
 * The **Expiry is required and lives here**, not on the request (#71). A strike and a
 * side name two different instruments once two series trade, so a Leg without one is
 * ambiguous — and the ambiguity would be resolved by a default nobody sees applied.
 * Spelled `10FEB26`, exactly as `ChainResponse.expiry` and the dropdown spell it.
 */
export interface LegRequest {
  strike: number;
  option_type: OptionType;
  expiry: string;
  direction: Direction;
  quantity?: number;
  /** Absent means "use the Chain's last traded price". Never send 0 to mean absent. */
  entry_premium?: number | null;
}

/**
 * One Strategy, as-of one moment. The moment is the request's; the Expiry is each Leg's.
 *
 * A Strategy whose Legs span two Expiries comes back **422 with a sentence naming both**,
 * not a curve: at the near Expiry the far Leg has not expired, so there is no single
 * Expiry line to draw. `ApiError.message` carries that sentence.
 */
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

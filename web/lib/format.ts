/**
 * Display rules, in one place because most of them are correctness rules wearing a
 * formatting hat.
 *
 * The two that matter most:
 *
 *  - **Times are UTC in the data and IST on screen.** `docs/data-quality.md` records
 *    that getting this backwards returns wrong or zero rows *silently*, which is the
 *    worst kind of wrong. Every moment on the wire is UTC; nothing renders one raw.
 *  - **An absent bound is the word "Unlimited"** (`CONTEXT.md`). Never `∞`, never
 *    `Infinity`, never blank, and never a very large number — all four read as a value.
 */

const IST_OFFSET_MINUTES = 5 * 60 + 30;

/** `2026-01-27T06:30:00` (UTC) → `12:00`, the clock a trader in India was watching. */
export function istClock(moment: string): string {
  const utc = new Date(`${moment}Z`);
  const ist = new Date(utc.getTime() + IST_OFFSET_MINUTES * 60_000);
  return `${String(ist.getUTCHours()).padStart(2, "0")}:${String(ist.getUTCMinutes()).padStart(2, "0")}`;
}

/** The full IST stamp, for the header. */
export function istStamp(moment: string): string {
  return `${istClock(moment)} IST`;
}

export function price(value: number): string {
  return value.toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function level(value: number): string {
  return value.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

export function strike(value: number): string {
  return value.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

/** Open interest and volume are counts; thousands separators, no decimals. */
export function count(value: number): string {
  return value.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

/** A decimal volatility as the percentage a trader reads. `0.164337` → `16.43%`. */
export function volatility(value: number | null): string {
  return value === null ? "" : `${(value * 100).toFixed(2)}%`;
}

/**
 * `null` is Unlimited. This is the function that keeps that promise, so it is the one
 * place to look if an `∞` ever reaches the screen.
 */
export function bound(value: number | null): string {
  return value === null ? "Unlimited" : price(value);
}

/** A ratio against an Unlimited gain has no meaning, so it is not shown as a number. */
export function ratio(value: number | null): string {
  return value === null ? "—" : value.toFixed(2);
}

export function signed(value: number, digits = 2): string {
  return `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(digits)}`;
}

/** Greeks span 25,219 and 0.00047, so the small ones need their own precision. */
export function greek(name: string, value: number): string {
  const digits = name === "gamma" ? 6 : name === "delta" ? 4 : 2;
  return value.toFixed(digits);
}

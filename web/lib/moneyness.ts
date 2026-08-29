import type { OptionType } from "@/lib/types";

/**
 * Whether a contract has intrinsic value at this moment.
 *
 * **Against the Forward, never against Spot.** The chain is priced off the Forward
 * (ADR-0001: the core takes a Forward and a Discount Factor, never a Spot and a rate),
 * the starred strike is the one nearest the Forward, and the basis reaches +118.87 - so
 * the two references genuinely disagree, and a table that used one rule for the star and
 * another for the shading would be showing two different markets at once.
 *
 * A strike sitting exactly on the Forward is in the money on **neither** side. Both
 * comparisons are strict, so no strike is ever shaded twice and the boundary belongs to
 * nobody, which is the honest answer for a contract with no intrinsic value either way.
 */
export function inTheMoney(strike: number, forward: number, optionType: OptionType): boolean {
  return optionType === "CE" ? strike < forward : strike > forward;
}

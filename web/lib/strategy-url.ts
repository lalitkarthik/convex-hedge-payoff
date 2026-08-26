/**
 * Reading and writing the two search parameters both pages share.
 *
 * `?moment=` and `?legs=` are the whole of the application's state (#32). Keeping the
 * reading in one place matters because both pages must interpret a link identically —
 * `/` and `/analyse` differ in what they render, never in what the URL means.
 *
 * A malformed `legs` throws out of `decodeLegs`; this module does not swallow it. The
 * pages catch it and say so, because the alternative is analysing a subset of the
 * Strategy the link names.
 */

import { decodeLegs, encodeLegs } from "./legs-url";
import type { LegRequest, SessionResponse } from "./types";

/**
 * 06:30 UTC = 12:00 IST.
 *
 * Named rather than computed as a midpoint: the session's 376 minutes are only the ones
 * that quoted, so they are not contiguous and the midpoint lands at 12:23. Every
 * published figure in `docs/calculations.md` was measured here.
 */
export const ANCHOR = "2026-01-27T06:30:00";

/** One search parameter, whether Next hands it over as a string or an array. */
export function one(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/**
 * The moment to render: what was asked for, if the session has it.
 *
 * A moment that is not in the session would 500 out of `/chain`, and the likeliest way
 * to hold one is a hand-edited or truncated link. Falling back to the anchor shows a
 * real chain instead of an error page.
 */
export function pickMoment(session: SessionResponse, asked: string | undefined): string {
  if (asked && session.moments.includes(asked)) return asked;
  return session.moments.includes(ANCHOR) ? ANCHOR : session.moments[0];
}

/** Build a link to either page, carrying the state across. */
export function strategyHref(
  path: "/" | "/analyse",
  moment: string,
  legs: LegRequest[],
): string {
  const params = new URLSearchParams({ moment });
  if (legs.length) params.set("legs", encodeLegs(legs));
  return `${path}?${params}`;
}

export { decodeLegs, encodeLegs };

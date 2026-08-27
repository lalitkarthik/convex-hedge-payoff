/**
 * Reading and writing the search parameters both pages share.
 *
 * `?date=`, `?expiry=`, `?moment=` and `?legs=` are the whole of the application's state
 * (#32). Keeping the reading in one place matters because both pages must interpret a
 * link identically — `/` and `/analyse` differ in what they render, never in what the
 * URL means.
 *
 * `date` and `expiry` joined the other two with #68, which is what makes a copied link
 * reopen the same view rather than the same minute of whichever day the engine defaults
 * to. **Neither is trusted as written.** A link is hand-editable and the dataset widens
 * with a build re-run, so what a page renders is the pair `/session` resolved — see
 * `pickView` — and not the pair the URL asked for.
 *
 * A malformed `legs` throws out of `decodeLegs`; this module does not swallow it. The
 * pages catch it and say so, because the alternative is analysing a subset of the
 * Strategy the link names.
 */

import { decodeLegs, encodeLegs } from "./legs-url";
import type { LegRequest, SessionResponse } from "./types";

/**
 * What a link addresses, once the engine has had its say: one date, one Expiry, one
 * minute. Every navigation writes all three, so no page ever holds two of them from one
 * view and the third from another.
 */
export interface View {
  date: string;
  expiry: string;
  moment: string;
}

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
 * The moment to render: what was asked for, if this session has it.
 *
 * A moment that is not in the session would 500 out of `/chain`, and there are now two
 * ordinary ways to hold one. A hand-edited or truncated link is the first. The second
 * arrived with #68: **the date changed under the moment.** A trader reading 12:00 on the
 * anchor picks 7 January, and `2026-01-27T06:30:00` is not a minute of that day.
 *
 * So the clock time is kept where the day has it. Landing at the same time of day is the
 * continuation of what the trader was doing; landing at the open is a different question
 * being answered. Where that minute did not quote — the sparse days are full of gaps —
 * the fallback is the anchor if this session has it, and otherwise the first minute the
 * day did quote.
 */
export function pickMoment(session: SessionResponse, asked: string | undefined): string {
  if (asked && session.moments.includes(asked)) return asked;

  // Same wall clock, different day. The stamps are fixed-width ISO 8601, so the time is
  // the tail after the `T` — compared as text rather than parsed, because these are the
  // engine's own strings and re-formatting them is how a spelling drifts.
  const clock = asked?.slice(10);
  const sameTime = clock ? session.moments.find((stamp) => stamp.endsWith(clock)) : undefined;
  if (sameTime) return sameTime;

  return session.moments.includes(ANCHOR) ? ANCHOR : session.moments[0];
}

/**
 * The view to render: the pair the **engine** resolved, at the best available minute.
 *
 * `session.date` and `session.expiry` rather than the URL's, and that is the whole
 * mechanism behind #68's "resolves to a valid pair rather than an empty Chain". The
 * server is asked for the pair the link named; it answers with one the store actually
 * holds, which is the same pair when the link was good. A client that echoed its own
 * request back would be asserting something it cannot know.
 */
export function pickView(session: SessionResponse, asked: string | undefined): View {
  return {
    date: session.date,
    expiry: session.expiry,
    moment: pickMoment(session, asked),
  };
}

/**
 * Build a link to either page, carrying the whole view across.
 *
 * All three are written every time, even where one is the engine's default. A link that
 * omitted the date would mean "whatever day the engine opens on", which is a different
 * thing from the day the sender was looking at and drifts from it the moment the anchor
 * moves.
 */
export function strategyHref(
  path: "/" | "/analyse",
  view: View,
  legs: LegRequest[],
): string {
  const params = new URLSearchParams({
    date: view.date,
    expiry: view.expiry,
    moment: view.moment,
  });
  if (legs.length) params.set("legs", encodeLegs(legs));
  return `${path}?${params}`;
}

export { decodeLegs, encodeLegs };

"use client";

import type { SessionResponse } from "@/lib/types";

/**
 * The two dropdowns above the Chain: a **date**, then an **Expiry** (#68).
 *
 * In that order because that is the order a trader works — a day first, then what that
 * day offered — and because the pairing runs that way: which Expiries exist is a
 * question about a date, not the reverse.
 *
 * **Neither list is read from a file.** Both arrive on the `/session` response, which is
 * the engine describing its own store. The alternative this replaces is a build script
 * writing a list beside the data, which is free to drift from it silently and fails at
 * the point a trader clicks rather than at the point it drifted.
 *
 * `session.expiries` holds only what traded on `session.date`, so no combination offered
 * here can return an empty Chain. Changing the date narrows the second list, and if the
 * held Expiry is not in the narrowed one the **engine** resolves the pair — `page.tsx`
 * renders `session.date` and `session.expiry` rather than what it asked for, so the
 * selection shown is always one that exists.
 *
 * Exactly one Expiry exists in this dataset, so the second control has one option today.
 * It is a dropdown anyway: an interface that showed text until a second series appeared
 * would be an interface nobody had ever run against two.
 */
export default function ViewPicker({
  session,
  onDate,
  onExpiry,
}: {
  session: SessionResponse;
  onDate: (date: string) => void;
  onExpiry: (expiry: string) => void;
}) {
  return (
    <>
      <label className="picker">
        <span className="stat-label">Date</span>
        <select
          className="picker-select"
          value={session.date}
          onChange={(event) => onDate(event.target.value)}
          aria-label="trading date"
        >
          {session.dates.map((date) => (
            <option key={date} value={date}>
              {readable(date)}
            </option>
          ))}
        </select>
      </label>

      <label className="picker">
        <span className="stat-label">Expiry</span>
        <select
          className="picker-select"
          value={session.expiry}
          onChange={(event) => onExpiry(event.target.value)}
          aria-label="expiry"
          disabled={session.expiries.length < 2}
          title={
            session.expiries.length < 2
              ? `${session.date} traded one series, so there is nothing to switch to`
              : undefined
          }
        >
          {session.expiries.map((expiry) => (
            <option key={expiry} value={expiry}>
              {expiry}
            </option>
          ))}
        </select>
      </label>
    </>
  );
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/**
 * `2026-01-27` → `27 Jan 2026`. Sliced rather than parsed into a `Date`.
 *
 * A trading date is a calendar fact with no time and no zone, and `new Date("2026-01-27")`
 * makes it midnight UTC — which renders as the 26th for anyone west of Greenwich. The
 * value passed back to the engine is the untouched string either way; only the label is
 * built here.
 */
function readable(date: string): string {
  const [year, month, day] = date.split("-");
  return `${Number(day)} ${MONTHS[Number(month) - 1]} ${year}`;
}

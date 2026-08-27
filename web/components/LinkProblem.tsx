import Link from "next/link";

import { strategyHref, type View } from "@/lib/strategy-url";

/**
 * A link that names a Strategy nobody can read.
 *
 * Shown instead of a chart, never alongside one. The failure being avoided is the quiet
 * one: a link carrying nine Legs, truncated by a chat client to eight and a half, and a
 * page that renders the eight it could parse. The chart would be wrong and nothing on
 * screen would say so.
 *
 * #31 owns the real error contract — a stable machine-readable code beside the message.
 * This is the honest placeholder: say what could not be read, and offer the way back.
 */
export default function LinkProblem({
  message,
  view,
  heading = "This link does not describe a Strategy",
  because = "Nothing has been analysed, because analysing part of a Strategy would show a chart of a position that was never built.",
}: {
  message: string;
  view: View;
  /**
   * Overridden for the second way a link can fail (#71): its Legs span two Expiries.
   *
   * That link *does* describe a Strategy — it describes one there is no Expiry line for,
   * because at the near Expiry the far Leg has not expired. Saying it could not be read
   * would be a different and untrue complaint, and the trader would go looking for a typo.
   */
  heading?: string;
  because?: string;
}) {
  return (
    <div className="problem">
      <h1>{heading}</h1>
      <p className="problem-detail">{message}</p>
      <p>{because}</p>
      {/* The date and the Expiry survive the unreadable Legs: only the Strategy could
          not be read, and dropping the view as well would send a trader back to a
          different day than the one their link named (#68). */}
      <Link className="problem-back" href={strategyHref("/", view, [])}>
        Start from the Chain →
      </Link>
    </div>
  );
}

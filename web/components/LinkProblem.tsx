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
}: {
  message: string;
  view: View;
}) {
  return (
    <div className="problem">
      <h1>This link does not describe a Strategy</h1>
      <p className="problem-detail">{message}</p>
      <p>
        Nothing has been analysed, because analysing part of a Strategy would show a chart
        of a position that was never built.
      </p>
      {/* The date and the Expiry survive the unreadable Legs: only the Strategy could
          not be read, and dropping the view as well would send a trader back to a
          different day than the one their link named (#68). */}
      <Link className="problem-back" href={strategyHref("/", view, [])}>
        Start from the Chain →
      </Link>
    </div>
  );
}

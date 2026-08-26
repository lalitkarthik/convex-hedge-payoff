import Link from "next/link";

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
  moment,
}: {
  message: string;
  moment: string;
}) {
  return (
    <div className="problem">
      <h1>This link does not describe a Strategy</h1>
      <p className="problem-detail">{message}</p>
      <p>
        Nothing has been analysed, because analysing part of a Strategy would show a chart
        of a position that was never built.
      </p>
      <Link className="problem-back" href={`/?moment=${encodeURIComponent(moment)}`}>
        Start from the Chain →
      </Link>
    </div>
  );
}

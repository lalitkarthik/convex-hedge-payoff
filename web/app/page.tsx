import Terminal from "@/components/Terminal";
import { readChain, readSession } from "@/lib/server-fixtures";

/**
 * A **server component**, which is #17's answer and not an incidental choice: the page
 * fetches the initial Chain, and the table and panel below it are client components
 * because selection state and the chart are inherently interactive.
 *
 * Fetching here means the first paint already has 91 strikes in it. It also means the
 * markup a browser receives contains the real table, so the page can be read without
 * running any JavaScript at all — which is how anyone checks the numbers are the ones
 * the engine produced.
 *
 * It opens on the **anchor minute**, 12:00 IST, where every published figure in
 * `docs/calculations.md` was measured.
 */
/**
 * 12:00 IST = 06:30 UTC. Named rather than computed as a midpoint: the session's 376
 * minutes are only the ones that quoted, so they are not contiguous and the midpoint
 * lands at 12:23. Every published figure in `docs/calculations.md` was measured here.
 */
const ANCHOR = "2026-01-27T06-30-00";

export default async function Page() {
  const session = await readSession();
  const found = session.moments.indexOf(ANCHOR);
  const opening = found === -1 ? Math.floor(session.moments.length / 2) : found;
  const chain = await readChain(session.moments[opening]);

  return <Terminal session={session} initialChain={chain} initialIndex={opening} />;
}

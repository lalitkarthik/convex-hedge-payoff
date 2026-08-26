import ChainScreen from "@/components/ChainScreen";
import LinkProblem from "@/components/LinkProblem";
import { getChain, getSession } from "@/lib/api";
import { LegsUrlError } from "@/lib/legs-url";
import { decodeLegs, one, pickMoment } from "@/lib/strategy-url";

/**
 * **The Chain.** Where a Strategy is built.
 *
 * A server component, which is #17's answer and not an incidental choice: the page
 * fetches the session and the chain, and only the table below it is a client component
 * because selection is inherently interactive.
 *
 * Fetching here means the first paint already has 91 strikes in it, and that the markup
 * a browser receives contains the real table — so the page can be read without running
 * any JavaScript at all, which is how anyone checks the numbers are the engine's.
 *
 * The state it renders comes entirely from the URL. Picking a Leg or moving the time
 * control rewrites the address bar, this component runs again, and the server returns
 * the chain for the new minute. One data path, and it is the same one a pasted link
 * takes.
 */

export const dynamic = "force-dynamic";
//: The chain is a function of a search parameter and the backend is live; a statically
//: rendered copy would be one minute of one day, served forever.

export default async function ChainPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const session = await getSession();
  const moment = pickMoment(session, one(params.moment));

  let legs;
  try {
    legs = decodeLegs(one(params.legs));
  } catch (error) {
    if (!(error instanceof LegsUrlError)) throw error;
    return <LinkProblem message={error.message} moment={moment} />;
  }

  const chain = await getChain(moment);

  return <ChainScreen session={session} chain={chain} legs={legs} />;
}

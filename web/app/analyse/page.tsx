import AnalyseScreen from "@/components/AnalyseScreen";
import LinkProblem from "@/components/LinkProblem";
import { getChain, getSession, postAnalysis } from "@/lib/api";
import { LegsUrlError } from "@/lib/legs-url";
import { decodeLegs, one, pickMoment } from "@/lib/strategy-url";

/**
 * **Analyse.** Where a Strategy is judged.
 *
 * A page of its own rather than a panel beside the chain, and the difference is not
 * cosmetic: it has an **address**. A trader builds a position, lands here, and the URL
 * they copy reproduces this exact screen in a cold tab — which is user story 37, and the
 * reason #32 puts Strategy state in search parameters rather than in a store.
 *
 * **Every number below comes from one `POST /analyse`.** The curve, the metrics, the
 * per-Leg Greeks and the payoff table arrive together (#23), so they cannot be as-of
 * different moments and cannot disagree. Nothing on this page computes anything: the
 * file that used to — `lib/skeleton-maths.ts`, a second implementation of
 * `strategy.py` — was deleted when this was wired, which is what it was quarantined for.
 *
 * The chain is fetched alongside because the header shows spot, the forward and the
 * basis, and because a Leg is labelled by its strike's implied volatility.
 */

export const dynamic = "force-dynamic";

export default async function AnalysePage({
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

  // Two requests, not one, and deliberately: the analysis is the Strategy's, the chain
  // is the market's. Bundling them would put a 91-strike table inside every response to
  // a question about four Legs.
  const [chain, analysis] = await Promise.all([
    getChain(moment),
    postAnalysis({ moment, legs }),
  ]);

  return (
    <AnalyseScreen
      session={session}
      chain={chain}
      analysis={analysis}
      legs={legs}
      moment={moment}
    />
  );
}

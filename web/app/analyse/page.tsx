import AnalyseScreen from "@/components/AnalyseScreen";
import LinkProblem from "@/components/LinkProblem";
import { ApiError, getSession, getSummary, postAnalysis } from "@/lib/api";
import { LegsUrlError } from "@/lib/legs-url";
import { decodeLegs, one, pickView } from "@/lib/strategy-url";

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
 * The **summary** is fetched alongside, and it used to be the whole Chain: the header
 * shows Spot, the Forward, the Discount Factor and the at-the-money volatility, and this
 * page was pulling 91 strikes across the wire to render four numbers. Since #69 those
 * four are a row of their own, so nothing on this screen reads the Chain artifact.
 */

export const dynamic = "force-dynamic";

export default async function AnalysePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;

  // The same resolution the Chain does, and it has to be the same: `/` and `/analyse`
  // differ in what they render, never in what a link means (#68).
  const session = await getSession(one(params.date), one(params.expiry));
  const view = pickView(session, one(params.moment));

  let legs;
  try {
    legs = decodeLegs(one(params.legs));
  } catch (error) {
    if (!(error instanceof LegsUrlError)) throw error;
    return <LinkProblem message={error.message} view={view} />;
  }

  // Two requests, not one, and deliberately: the analysis is the Strategy's, the summary
  // is the market's. Bundling them would put the market inside every response to a
  // question about four Legs.
  let summary, analysis;
  try {
    [summary, analysis] = await Promise.all([
      getSummary(view.moment, view.date, view.expiry),
      postAnalysis({ moment: view.moment, legs }),
    ]);
  } catch (error) {
    // A Strategy the engine will not chart, which since #71 is a link a person can hold:
    // the dropdown clears the Legs when the series changes, so the only way to build one
    // spanning two Expiries is to write it. #64's story 14 asks for that to be said
    // plainly — a Next error boundary would say "Application error", and the sentence the
    // engine wrote explaining exactly which two series were named would never be read.
    if (!(error instanceof ApiError) || error.status !== 422) throw error;
    return (
      <LinkProblem
        heading="This Strategy has no Expiry line"
        message={error.detail}
        because="Nothing has been charted, because a curve drawn across two Expiries looks like an answer and is not one."
        view={view}
      />
    );
  }

  return (
    <AnalyseScreen
      session={session}
      summary={summary}
      analysis={analysis}
      legs={legs}
      view={view}
    />
  );
}

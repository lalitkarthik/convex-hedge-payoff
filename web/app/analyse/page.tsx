import AnalyseScreen from "@/components/AnalyseScreen";
import LinkProblem from "@/components/LinkProblem";
import { ApiError, getChain, getSession, getSummary, postAnalysis } from "@/lib/api";
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
 * The **summary** is fetched alongside: the header shows Spot, the Forward, the Discount
 * Factor and the at-the-money volatility, and since #69 those four are a row of their own
 * rather than a reduction of 91 strikes.
 *
 * The **Chain** is fetched too, and it was not always. It was dropped here when the
 * summary landed, on the grounds that this page was pulling 91 strikes across the wire to
 * render four numbers - true at the time. It is back because the strike slider needs a
 * ladder to drag along, and that ladder cannot be synthesised: the quoted set is
 * per-minute *and* per-side, it has holes in it, and `strike_min`/`strike_max` describe
 * the whole day. The 91 rows are now the thing being used rather than the thing being
 * reduced, and they join the same `Promise.all`, so this costs a payload and not a wave.
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
  let summary, analysis, chain;
  try {
    [summary, analysis, chain] = await Promise.all([
      getSummary(view.moment, view.date, view.expiry),
      postAnalysis({ moment: view.moment, legs }),
      getChain(view.moment, view.date, view.expiry),
    ]);
  } catch (error) {
    // A Strategy the engine will not chart, which since #71 is a link a person can hold:
    // the dropdown clears the Legs when the series changes, so the only way to build one
    // spanning two Expiries is to write it. #64's story 14 asks for that to be said
    // plainly — a Next error boundary would say "Application error", and the sentence the
    // engine wrote explaining exactly which two series were named would never be read.
    if (!(error instanceof ApiError)) throw error;

    // A Leg naming an instrument with no bar at or before this minute. Reachable
    // without a malformed link: the quoted set grows through the session, so a
    // Strategy built at noon and dragged backwards through the time control arrives
    // here. The engine names the strike and the side, which is the whole message.
    if (error.status === 404) {
      return (
        <LinkProblem
          heading="One of these Legs is not quoted at this minute"
          message={error.detail}
          because="Nothing has been charted, because a curve missing a Leg is a curve of a position nobody holds. Move to a later minute, or drop the Leg."
          view={view}
        />
      );
    }

    if (error.status !== 422) throw error;
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
      chain={chain}
      legs={legs}
      view={view}
    />
  );
}

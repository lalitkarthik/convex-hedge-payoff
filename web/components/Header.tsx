import type { ChainResponse } from "@/lib/types";
import { level, signed } from "@/lib/format";

/**
 * Spot, the **Forward** and the basis — the figures that belong to the *minute*.
 *
 * The Forward is here because the at-the-money strike is chosen by it, not by spot. At
 * the anchor the basis is +118.87 — more than two 50-point intervals — so the starred
 * strike is 25,200 while spot reads 25,100.25. Without the Forward on screen that looks
 * like a bug rather than a decision (#51).
 *
 * **Which day and which series is not this component's business** (#68). It was, while
 * the Expiry was one fixed label rendered as text; now the Chain carries two dropdowns
 * and Analyse carries two chips, and both arrive as `children`. Rendering it here as
 * well would show a trader the Expiry twice, once selectable and once not.
 *
 * Nothing invented — no futures price, no INDIAVIX, no IV percentile. Sensibull shows
 * all three; none exists in this data. A fitted Forward is not an exception: a futures
 * price would be an *observation* and there is no futures series to observe, while the
 * Forward is *derived* from the option prices by put-call parity.
 */
export default function Header({ chain, children }: { chain: ChainResponse; children?: React.ReactNode }) {
  const basis = chain.forward - chain.spot;
  const assumed = chain.forward_method !== "parity_fit";

  return (
    <header className="header">
      <div className="brand">NIFTY</div>

      <div className="stat">
        <span className="stat-label">Spot</span>
        <span className="stat-value">{level(chain.spot)}</span>
      </div>

      <div className="stat">
        <span className="stat-label">Forward</span>
        <span className="stat-value">
          {level(chain.forward)} <span className="stat-note">({signed(basis)})</span>
        </span>
      </div>

      {assumed && (
        <span className="chip" title="The regression could not be trusted at this minute, so the Forward is assumed rather than measured (#51).">
          forward assumed · {chain.forward_method.replace(/_/g, " ")}
        </span>
      )}

      {children}
    </header>
  );
}

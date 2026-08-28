import ThemeToggle from "@/components/ThemeToggle";
import type { SummaryResponse } from "@/lib/types";
import { level, signed, volatility } from "@/lib/format";

/**
 * Spot, the **Forward**, the Discount Factor and the at-the-money volatility — the four
 * figures that belong to the *minute*.
 *
 * **It reads a summary, not the Chain (#69).** All four repeat across every strike of the
 * minute in the stored Chain, so showing them meant reading the artifact that holds
 * 1,062,024 rows to take four numbers. They come from `/summary` now, one row a minute,
 * and dragging the time control moves them 375 times without touching the Chain.
 *
 * The Forward is here because the at-the-money strike is chosen by it, not by spot. At
 * the anchor the basis is +118.87 — more than two 50-point intervals — so the starred
 * strike is 25,200 while spot reads 25,100.25. Without the Forward on screen that looks
 * like a bug rather than a decision (#51).
 *
 * The volatility is labelled with the strike it belongs to, because it is one strike's
 * and not the session's: an unlabelled "IV" beside a Spot reads as a level for the index.
 * It goes blank rather than to zero where the print no volatility reproduces — the last
 * minute of Expiry day is every strike at once — which is `ChainRow.iv`'s rule one field
 * along.
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
export default function Header({
  summary,
  children,
}: {
  summary: SummaryResponse;
  children?: React.ReactNode;
}) {
  const basis = summary.forward - summary.spot;
  const assumed = summary.forward_method !== "parity_fit";

  return (
    <header className="header">
      <div className="brand">NIFTY</div>

      <div className="stat">
        <span className="stat-label">Spot</span>
        <span className="stat-value">{level(summary.spot)}</span>
      </div>

      <div className="stat">
        <span className="stat-label">Forward</span>
        <span className="stat-value">
          {level(summary.forward)} <span className="stat-note">({signed(basis)})</span>
        </span>
      </div>

      <div className="stat">
        <span className="stat-label">Discount</span>
        <span className="stat-value">{summary.discount.toFixed(4)}</span>
      </div>

      <div className="stat">
        <span className="stat-label">ATM IV</span>
        <span className="stat-value">
          {summary.atm_iv === null ? "—" : volatility(summary.atm_iv)}{" "}
          <span className="stat-note">({level(summary.atm_strike)})</span>
        </span>
      </div>

      {assumed && (
        <span className="chip" title="The regression could not be trusted at this minute, so the Forward is assumed rather than measured (#51).">
          forward assumed · {summary.forward_method.replace(/_/g, " ")}
        </span>
      )}

      {children}
      {/* Last, and pushed right by `margin-left: auto`: it changes how the figures look
          and never what they say, so it must not sit among them competing for the eye. */}
      <ThemeToggle />
    </header>
  );
}

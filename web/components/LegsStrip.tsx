"use client";

import type { LegRequest } from "@/lib/types";
import { strike as fmtStrike } from "@/lib/format";

/**
 * Direction, quantity, strike, type, Entry Premium.
 *
 * **Entry Premium is editable** and defaults to the chain's last traded price. That is
 * the one price a trader may legitimately supply (story 18, "what if I had entered at
 * X") — and it matters here because Breakevens are entirely determined by entry prices,
 * and a stale in-the-money print is a real risk: the model price equals `last` on 100%
 * of out-of-the-money rows and only 6.2% of in-the-money ones.
 *
 * Direction is separate from Quantity (`CONTEXT.md`): sold two is direction −1 and
 * quantity 2, never quantity −2. The two encodings draw the same curve today and
 * disagree the first time anything sums or displays Quantity.
 */
export default function LegsStrip({
  legs,
  onChange,
  onRemove,
  readOnly = false,
  selected,
  onSelect,
}: {
  legs: LegRequest[];
  onChange?: (index: number, leg: LegRequest) => void;
  onRemove?: (index: number) => void;
  /** Direction, Quantity and Entry Premium are not edited on the Analyse page.
      The strike now is, through `StrikeSlider` - and the objection this flag used to
      carry, that the quote a Leg is priced against lives on the Chain, is answered
      rather than waived: Analyse fetches the Chain, the slider offers only strikes it
      actually quotes, and moving one drops the Entry Premium so the engine reprices
      against the quote at the new strike. What is still refused here is editing a
      price by hand, away from any quote at all. */
  readOnly?: boolean;
  /** Which Leg the strike slider is pointed at. Interface state, deliberately not in
      the URL: #32 puts the *Strategy* in the address bar, and which row is highlighted
      is not part of the Strategy - a shared link would otherwise carry it. */
  selected?: number;
  onSelect?: (index: number) => void;
}) {
  if (legs.length === 0) {
    return (
      <div className="empty">
        No Legs yet — click <strong>B</strong> or <strong>S</strong> on the Chain, or pick a Preset.
      </div>
    );
  }

  return (
    <div className="legs">
      {legs.map((leg, index) => (
        <div
          className={`leg ${onSelect && selected === index ? "selected" : ""}`}
          key={`${leg.strike}${leg.option_type}${index}`}
          // The row is the target rather than a separate radio: it is already the thing
          // that names the Leg, and a second control beside it would say there are two.
          onClick={onSelect ? () => onSelect(index) : undefined}
        >
          <button
            className={`dir ${leg.direction === 1 ? "b" : "s"}`}
            title="Flip between bought and sold"
            disabled={readOnly}
            onClick={() => onChange?.(index, { ...leg, direction: leg.direction === 1 ? -1 : 1 })}
          >
            {leg.direction === 1 ? "B" : "S"}
          </button>

          <span className={onSelect ? "leg-pick" : undefined}>
            {fmtStrike(leg.strike)} {leg.option_type}
          </span>

          <input
            type="number"
            min={1}
            step={1}
            value={leg.quantity ?? 1}
            aria-label="quantity"
            readOnly={readOnly}
            onChange={(event) =>
              onChange?.(index, { ...leg, quantity: Math.max(1, Number(event.target.value) || 1) })
            }
          />

          {/*
            Blank, not zero, when the Leg carries no Entry Premium. Absent means "price
            it at the Chain's last traded price", and until the strike slider existed
            every Leg reached this component with a premium already on it, so the `?? 0`
            this replaces never fired. It fires now on any Leg that has been moved - and
            a 0 in this box says the trader entered the position for nothing, which is
            the same false reading `legs-url.ts` refuses to write into the URL.
          */}
          <input
            type="number"
            step={0.05}
            value={leg.entry_premium ?? ""}
            placeholder="chain"
            title={
              leg.entry_premium === undefined || leg.entry_premium === null
                ? "Priced at the Chain's last traded price for this strike"
                : "Entry Premium"
            }
            aria-label="entry premium"
            readOnly={readOnly}
            onChange={(event) =>
              onChange?.(index, { ...leg, entry_premium: Number(event.target.value) })
            }
          />

          {!readOnly && (
            <button className="drop" onClick={() => onRemove?.(index)} aria-label="remove leg">
              ×
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

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
}: {
  legs: LegRequest[];
  onChange?: (index: number, leg: LegRequest) => void;
  onRemove?: (index: number) => void;
  /** The Analyse page shows the Legs beside the numbers but does not edit them - the
      quote a Leg is priced against lives on the Chain, and editing away from it would
      be editing blind. */
  readOnly?: boolean;
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
        <div className="leg" key={`${leg.strike}${leg.option_type}${index}`}>
          <button
            className={`dir ${leg.direction === 1 ? "b" : "s"}`}
            title="Flip between bought and sold"
            disabled={readOnly}
            onClick={() => onChange?.(index, { ...leg, direction: leg.direction === 1 ? -1 : 1 })}
          >
            {leg.direction === 1 ? "B" : "S"}
          </button>

          <span>
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

          <input
            type="number"
            step={0.05}
            value={leg.entry_premium ?? 0}
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

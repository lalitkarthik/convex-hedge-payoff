"use client";

import { useState } from "react";

import { nearestIndex } from "@/lib/strikes";
import { strike as fmtStrike } from "@/lib/format";
import type { OptionType } from "@/lib/types";

/**
 * Move one Leg along the strikes that are actually quoted.
 *
 * An index into a discrete ladder rather than a number with a step, because the strikes
 * are neither uniform nor constant: they are per-minute and per-side, the anchor's
 * ninety-one have three hundred-wide holes in them, and fifty of them quote one side
 * only. A `min`/`max`/`step` slider would look right and stop on strikes the engine
 * cannot price. See `lib/strikes.ts` - every rung here is one `/analyse` can answer.
 *
 * **It commits on release, not on every tick.** This is the one place it departs from
 * `TimeControl`, which is fully controlled and whose thumb only advances once the server
 * answers. That is fine for a control the trader nudges; dragging across twenty strikes
 * would be twenty navigations and sixty uncached backend calls, with the thumb snapping
 * backwards each time a slower one landed. So the drag is local and the URL is written
 * once, when the pointer or the key comes up.
 *
 * The keyboard case is not decoration: arrow keys fire `onChange` and never a pointer
 * event, so without `onKeyUp` this would be draggable but not operable.
 */
export default function StrikeSlider({
  strikes,
  strike,
  optionType,
  onCommit,
  disabled = false,
}: {
  strikes: number[];
  strike: number;
  optionType: OptionType;
  onCommit: (strike: number) => void;
  disabled?: boolean;
}) {
  // The committed position comes from the server, through the URL. `dragging` is the
  // only local state, and it exists for the length of one gesture.
  const committed = nearestIndex(strikes, strike);
  const [dragging, setDragging] = useState<number | null>(null);
  const index = dragging ?? committed;

  const last = strikes.length - 1;
  const shown = strikes[index] ?? strike;
  const idle = disabled || strikes.length === 0;

  function commit(next: number) {
    setDragging(null);
    const chosen = strikes[next];
    if (chosen !== undefined && chosen !== strike) onCommit(chosen);
  }

  if (strikes.length === 0) {
    return <div className="empty">Nothing is quoted for this side at this minute.</div>;
  }

  return (
    <div className="strike-slider">
      <div className="time-row">
        <button
          className="step"
          onClick={() => commit(index - 1)}
          disabled={idle || index <= 0}
          aria-label="lower strike"
        >
          ‹
        </button>
        <input
          type="range"
          min={0}
          max={last}
          value={index}
          disabled={idle}
          // Moves the label only. Nothing is fetched until the gesture ends.
          onChange={(event) => setDragging(Number(event.target.value))}
          onPointerUp={() => commit(index)}
          onKeyUp={() => commit(index)}
          // A pointer released outside the track still ends the gesture; without this
          // the thumb would stay parked on an uncommitted strike.
          onBlur={() => commit(index)}
          aria-label={`strike for the ${optionType} Leg`}
        />
        <button
          className="step"
          onClick={() => commit(index + 1)}
          disabled={idle || index >= last}
          aria-label="higher strike"
        >
          ›
        </button>
        <span className="stat-value strike-now">
          {fmtStrike(shown)} {optionType}
        </span>
      </div>
      <div className="time-ends">
        <span>{fmtStrike(strikes[0]!)}</span>
        <span>
          {index + 1} / {strikes.length} quoted
        </span>
        <span>{fmtStrike(strikes[last]!)}</span>
      </div>
    </div>
  );
}

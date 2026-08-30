"use client";

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
 * **It used to commit on release, and no longer needs to.** That existed because a tick
 * cost a navigation and four backend calls, so dragging across twenty strikes meant twenty
 * page renders with the thumb snapping backwards each time a slower one landed. A tick now
 * costs one throttled `POST /analyse` and no render at all, so the value goes up on every
 * change and the local drag state, the `onPointerUp`/`onKeyUp`/`onBlur` trio and the
 * keyboard special case all went with it. The component is fully controlled again, like
 * `TimeControl`, and the reason the two differed has been removed rather than worked
 * around.
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
  if (strikes.length === 0) {
    return <div className="empty">Nothing is quoted for this side at this minute.</div>;
  }

  // Nearest rather than `indexOf`: a Leg's strike can legitimately be off the ladder, if
  // it was built at a minute that quoted it and the time control has since moved.
  const index = nearestIndex(strikes, strike);
  const last = strikes.length - 1;

  function commit(next: number) {
    const chosen = strikes[next];
    if (chosen !== undefined && chosen !== strike) onCommit(chosen);
  }

  return (
    <div className="strike-slider">
      <div className="time-row">
        <button
          className="step"
          onClick={() => commit(index - 1)}
          disabled={disabled || index <= 0}
          aria-label="lower strike"
        >
          ‹
        </button>
        <input
          type="range"
          min={0}
          max={last}
          value={index}
          disabled={disabled}
          onChange={(event) => commit(Number(event.target.value))}
          aria-label={`strike for the ${optionType} Leg`}
        />
        <button
          className="step"
          onClick={() => commit(index + 1)}
          disabled={disabled || index >= last}
          aria-label="higher strike"
        >
          ›
        </button>
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

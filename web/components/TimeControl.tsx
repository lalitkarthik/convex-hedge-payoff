"use client";

import { istClock } from "@/lib/format";

/**
 * The session, as 376 positions — and **none of them disabled**.
 *
 * An earlier design disabled 60 of them, on the grounds that the put-call-parity
 * regression could not be trusted at those minutes. #51's fallback ladder removed that:
 * every minute now yields a Forward. Where one was assumed rather than measured, the
 * header says so — which is honest without refusing to show a chain that is perfectly
 * real.
 *
 * Labels are **IST**; the data underneath is UTC. `docs/data-quality.md` records that
 * getting that backwards returns wrong or zero rows *silently*.
 */
export default function TimeControl({
  moments,
  index,
  onChange,
}: {
  moments: string[];
  index: number;
  onChange: (next: number) => void;
}) {
  const last = moments.length - 1;

  return (
    <div className="time">
      <div className="time-row">
        <button
          className="step"
          onClick={() => onChange(index - 1)}
          disabled={index <= 0}
          aria-label="previous minute"
        >
          ‹
        </button>
        <input
          type="range"
          min={0}
          max={last}
          value={index}
          onChange={(event) => onChange(Number(event.target.value))}
          aria-label="moment"
        />
        <button
          className="step"
          onClick={() => onChange(index + 1)}
          disabled={index >= last}
          aria-label="next minute"
        >
          ›
        </button>
        <span className="stat-value" style={{ minWidth: 74, textAlign: "right" }}>
          {istClock(moments[index])} IST
        </span>
      </div>
      <div className="time-ends">
        <span>{istClock(moments[0])}</span>
        <span>
          {index + 1} / {moments.length}
        </span>
        <span>{istClock(moments[last])}</span>
      </div>
    </div>
  );
}

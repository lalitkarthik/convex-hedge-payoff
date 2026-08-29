"use client";

/**
 * Two mutually exclusive choices, both always visible.
 *
 * One component for B/S and for CE/PE, because they are the same control: a binary that
 * is part of the Leg's identity rather than a value being typed. Showing both halves and
 * lighting the live one says what the alternative *is*, which a single button reading "B"
 * does not - the Legs strip has always had one of those, and it needs a tooltip to
 * explain that clicking it flips to something the trader cannot see.
 *
 * `aria-pressed` on both halves rather than a radio group: they are buttons that act
 * immediately, and a change here re-prices the Leg rather than staging a form.
 */
export default function Toggle<T extends string>({
  options,
  value,
  onChange,
  label,
  tone,
  disabled,
}: {
  /** Exactly two, in the order they are drawn. */
  options: readonly [T, T];
  value: T;
  onChange: (next: T) => void;
  label: string;
  /** Which palette the lit half wears. `side` colours calls blue and puts red, matching
      the Chain's own column headings; `direction` does the same for bought and sold. */
  tone: "side" | "direction";
  disabled?: (option: T) => string | null;
}) {
  return (
    <span className={`toggle toggle-${tone}`} role="group" aria-label={label}>
      {options.map((option) => {
        const why = disabled?.(option) ?? null;
        return (
          <button
            key={option}
            className={`toggle-half ${option === value ? "on" : ""} t-${option.toLowerCase()}`}
            aria-pressed={option === value}
            // A choice that is already made is not a click worth making, and a choice
            // this minute cannot honour says why rather than simply failing to respond.
            disabled={option === value || why !== null}
            title={why ?? `${label}: ${option}`}
            onClick={() => onChange(option)}
          >
            {option}
          </button>
        );
      })}
    </span>
  );
}

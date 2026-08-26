"use client";

/**
 * The five Presets, which build exactly the Legs a trader would have picked by hand.
 *
 * That equivalence is the point: choosing a Preset and selecting its Legs off the Chain
 * are the same operation rather than two paths that happen to agree. The backend returns
 * Presets as **Leg requests**, not as an analysed result, for the same reason.
 *
 * Each is centred on the at-the-money strike — nearest the **Forward**, so 25,200.
 */
export default function PresetPicker({
  presets,
  onPick,
}: {
  presets: string[];
  onPick: (name: string) => void;
}) {
  return (
    <div className="presets">
      {presets.map((name) => (
        <button key={name} onClick={() => onPick(name)}>
          {name.replace(/_/g, " ")}
        </button>
      ))}
    </div>
  );
}

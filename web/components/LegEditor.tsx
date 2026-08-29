"use client";

import StrikeSlider from "./StrikeSlider";
import Toggle from "./Toggle";

import { strike as fmtStrike, price } from "@/lib/format";
import { addLeg, legalStrikes, moveLeg, nearestIndex } from "@/lib/strikes";
import type { ChainResponse, Direction, LegRequest } from "@/lib/types";

/**
 * The Strategy, editable, one card per Leg.
 *
 * A separate component from `LegsStrip` rather than a fifth optional prop on it. The two
 * screens now want genuinely different things: the Chain wants a compact list beside a
 * table it is already competing with for width, and Analyse wants room to change a Leg
 * without going anywhere. One component serving both would serve one of them badly.
 *
 * **Every control here is a contract change, so every control re-prices.** Direction is
 * the exception - which way a position was traded does not change what it costs - and it
 * is the only one that leaves `entry_premium` alone. Moving the strike or flipping the
 * side asks `lib/strikes.ts` for the new Leg, which reads the price off the Chain this
 * page already holds. That is why the Chain is fetched here at all.
 *
 * Direction stays separate from Quantity (`CONTEXT.md`): sold two is direction −1 and
 * quantity 2, never quantity −2. The two draw the same curve today and disagree the first
 * time anything sums or displays Quantity.
 *
 * Expiry is deliberately not editable. A Leg's series is chosen on the Chain, and letting
 * it change here would let one Strategy span two Expiries - which the engine refuses,
 * correctly, because at the near Expiry the far Leg has not expired and there is no single
 * Expiry line to draw.
 */
export default function LegEditor({
  legs,
  chain,
  onChange,
}: {
  legs: LegRequest[];
  chain: ChainResponse;
  onChange: (legs: LegRequest[]) => void;
}) {
  const calls = legalStrikes(chain.rows, "CE");

  function set(at: number, leg: LegRequest) {
    onChange(legs.map((existing, index) => (index === at ? leg : existing)));
  }

  return (
    <div className="leg-editor">
      {legs.length === 0 && (
        <div className="empty">
          No Legs. Add one below, or go back to the Chain and pick some.
        </div>
      )}

      {legs.map((leg, at) => {
        const ladder = legalStrikes(chain.rows, leg.option_type);

        return (
          /*
           * Keyed on position alone, and it has to be.
           *
           * The key used to carry the strike, which changes on every tick of a drag - so
           * React unmounted and remounted the card, destroying the `<input type="range">`
           * inside it. A pointer drag is captured by a DOM node, so replacing that node
           * ends the gesture: the thumb moved one strike and then stopped dead until the
           * mouse was released and pressed again.
           *
           * Nothing here needs remounting on a strike change. Every control is driven by
           * props, so React updating them in place is the whole point.
           */
          <div className="leg-card" key={at}>
            <div className="leg-card-row">
              <Toggle
                options={["B", "S"]}
                value={leg.direction === 1 ? "B" : "S"}
                label="Direction"
                tone="direction"
                // Direction alone does not change the contract, so the price it was
                // entered at survives the flip. Everything else on this card re-prices.
                onChange={(next) => set(at, { ...leg, direction: next === "B" ? 1 : (-1 as Direction) })}
              />
              <Toggle
                options={["CE", "PE"]}
                value={leg.option_type}
                label="Option type"
                tone="side"
                disabled={(option) =>
                  legalStrikes(chain.rows, option).length === 0
                    ? `Nothing is quoted on the ${option} side at this minute`
                    : null
                }
                onChange={(next) => onChange(moveLeg(legs, at, { option_type: next }, chain.rows))}
              />

              <span className="leg-name">
                {fmtStrike(leg.strike)} {leg.option_type}
              </span>

              <input
                type="number"
                min={1}
                step={1}
                value={leg.quantity ?? 1}
                aria-label="quantity"
                onChange={(event) =>
                  set(at, { ...leg, quantity: Math.max(1, Number(event.target.value) || 1) })
                }
              />

              {/* The Entry Premium, and it is a real number rather than a placeholder now.
                  Editable because it is the one price a trader may legitimately supply -
                  story 18, "what if I had entered at X" - and it is what determines the
                  Breakevens, so a stale in-the-money print is a real risk: the model price
                  equals `last` on 100% of out-of-the-money rows and 6.2% of in-the-money
                  ones. Moving the strike or the side overwrites it from the Chain. */}
              <input
                type="number"
                step={0.05}
                value={leg.entry_premium ?? ""}
                aria-label="entry premium"
                title={
                  leg.entry_premium === undefined || leg.entry_premium === null
                    ? "Not quoted at this strike — the engine will refuse this Leg"
                    : "Entry Premium, from the Chain unless you change it"
                }
                onChange={(event) => set(at, { ...leg, entry_premium: Number(event.target.value) })}
              />

              <button
                className="drop"
                onClick={() => onChange(legs.filter((_, index) => index !== at))}
                aria-label={`remove ${leg.strike} ${leg.option_type}`}
              >
                ×
              </button>
            </div>

            <StrikeSlider
              strikes={ladder}
              strike={leg.strike}
              optionType={leg.option_type}
              onCommit={(strike) => onChange(moveLeg(legs, at, { strike }, chain.rows))}
            />
          </div>
        );
      })}

      {/*
        At the money means nearest the *Forward*, which is the rule the starred strike and
        the in-the-money wash both follow. Disabled when this minute quotes no calls at
        all, which the early minutes of a date genuinely do - adding a Leg with no price
        would put the whole Strategy into the engine's refusal path and take the chart
        away as the cost of a click.
      */}
      <button
        className="add-leg"
        onClick={() => onChange(addLeg(legs, chain.rows, chain.forward, chain.expiry))}
        disabled={calls.length === 0}
        title={
          calls.length === 0
            ? "No calls are quoted at this minute"
            : `Add a bought call at ${fmtStrike(calls[nearestIndex(calls, chain.forward)]!)}, the strike nearest the Forward of ${price(chain.forward)}`
        }
      >
        + Add a Leg
      </button>
    </div>
  );
}

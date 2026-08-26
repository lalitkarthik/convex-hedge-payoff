/**
 * Where the numbers come from — and the one seam the real backend replaces.
 *
 * There is no server yet. Everything here is read out of `public/fixtures/`, which
 * `scripts/build_fixtures.py` wrote by driving the actual FastAPI app in-process. So the
 * figures on screen are the engine's own, not invented ones: a fabricated payoff curve
 * renders, looks right, and is exactly the failure this project exists to catch.
 *
 * **This file is the whole of the swap.** Point `chainUrl` at `/api/chain?moment=` and
 * the skeleton is talking to the backend; nothing else in `web/` knows where a chain
 * came from.
 */

import type { ChainResponse, LegRequest, Session } from "./types";

/** `2026-01-27 06:30:00` → `2026-01-27T06-30-00`, matching the fixture filenames. */
export function momentToStem(moment: string): string {
  return moment.replace(" ", "T").replaceAll(":", "-");
}

/** `2026-01-27T06-30-00` → `2026-01-27T06:30:00`, an ISO instant the browser parses. */
export function stemToIso(stem: string): string {
  const [date, clock] = stem.split("T");
  return `${date}T${clock.replaceAll("-", ":")}`;
}

function chainUrl(stem: string): string {
  return `/fixtures/chain/${stem}.json`;
}

async function readJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url} → ${response.status}`);
  return (await response.json()) as T;
}

export async function loadSession(): Promise<Session> {
  return readJson<Session>("/fixtures/session.json");
}

export async function loadChain(stem: string): Promise<ChainResponse> {
  return readJson<ChainResponse>(chainUrl(stem));
}

export async function loadPreset(name: string): Promise<LegRequest[]> {
  const body = await readJson<{ legs: LegRequest[] }>(`/fixtures/presets/${name}.json`);
  return body.legs;
}

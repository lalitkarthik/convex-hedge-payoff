import { readFile } from "node:fs/promises";
import path from "node:path";

import type { ChainResponse, Session } from "./types";

/**
 * The **server** half of the fixture seam, read off disk rather than over HTTP.
 *
 * #17's answer: *"the page is a server component that fetches the initial chain; the
 * chain table and the analysis panel are client components."* This is that fetch. The
 * first paint already has a chain in it, so nothing renders a "Loading…" flash on the
 * way to showing data that was on disk the whole time — and the markup a browser
 * receives contains the real table, which is what makes it inspectable without running
 * JavaScript.
 *
 * `lib/fixtures.ts` is the client half, for every moment after the first. Both point at
 * the same files, and both are what the real API replaces.
 */

const ROOT = path.join(process.cwd(), "public", "fixtures");

async function readJson<T>(...parts: string[]): Promise<T> {
  return JSON.parse(await readFile(path.join(ROOT, ...parts), "utf8")) as T;
}

export async function readSession(): Promise<Session> {
  return readJson<Session>("session.json");
}

export async function readChain(stem: string): Promise<ChainResponse> {
  return readJson<ChainResponse>("chain", `${stem}.json`);
}

/**
 * The only place in `web/` that knows a URL.
 *
 * This replaces `lib/fixtures.ts` and `lib/server-fixtures.ts`, which read the engine's
 * answers out of 382 committed JSON files. Those files were real output, but they were a
 * *second copy* of it, free to drift from the engine the day either changed. Now there
 * is one source of answers and the client asks it.
 *
 * **The client never prices.** Every number rendered anywhere downstream arrives from
 * one of these five calls. Nothing here computes a payoff, a metric or a Greek - the
 * deleted `skeleton-maths.ts` did, and that was a second implementation of
 * `strategy.py`, which is the duplication ADR-0001 exists to prevent.
 *
 * ## Where the request goes, and why it depends on who is asking
 *
 * A **browser** must stay same-origin: it calls `/api/...`, and `next.config.ts` rewrites
 * that to the backend. No cross-origin headers are ever configured, which is #25's rule
 * — *"a misconfigured cross-origin policy"* is the failure being designed out, and a
 * policy that does not exist cannot be misconfigured.
 *
 * A **server component** has no origin, so a relative path resolves to nothing and fails
 * at render time with `Failed to parse URL` — which reads like a bug in Next rather than
 * an unset environment variable. It uses `BACKEND_ORIGIN` directly.
 */

import type {
  AnalysisRequest,
  AnalysisResponse,
  ChainResponse,
  LegRequest,
  PresetResponse,
  SessionResponse,
} from "./types";

/** The dev default. Named here rather than inline so the failure message can point at it. */
export const LOCAL_BACKEND = "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly endpoint: string,
    detail: string,
  ) {
    super(`${endpoint} → ${status}${detail ? `: ${detail}` : ""}`);
    this.name = "ApiError";
  }
}

/** Exported so it can be asserted; the branch only misbehaves in server rendering. */
export function apiBase(
  where: { onServer: boolean; backendOrigin?: string | undefined } = {
    onServer: typeof window === "undefined",
    backendOrigin: process.env.BACKEND_ORIGIN,
  },
): string {
  if (!where.onServer) return "/api";
  return where.backendOrigin ?? LOCAL_BACKEND;
}

async function request<T>(endpoint: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase()}${endpoint}`, {
    // The chain moves minute by minute and an analysis is a pure function of its body;
    // neither is worth a stale cache entry, and Next caches `fetch` by default.
    cache: "no-store",
    ...init,
  });

  if (!response.ok) {
    // The body is read for its `detail`, which is what the server puts an explanation in
    // (`api.py`'s handler for an unknown preset). #31 formalises the shape; until then,
    // whatever is there beats "500".
    let detail = "";
    try {
      const body = (await response.json()) as { detail?: unknown };
      detail = typeof body?.detail === "string" ? body.detail : "";
    } catch {
      /* a non-JSON error body is not itself an error */
    }
    throw new ApiError(response.status, endpoint, detail);
  }

  return (await response.json()) as T;
}

/** The day: which minutes exist, what expires, what the picker offers. Asked once. */
export function getSession(): Promise<SessionResponse> {
  return request<SessionResponse>("/session");
}

export function getChain(moment: string): Promise<ChainResponse> {
  return request<ChainResponse>(`/chain?moment=${encodeURIComponent(moment)}`);
}

/**
 * Everything about one Strategy, in one response (#23).
 *
 * One request rather than four, so the curve, the metrics, the Greeks and the table are
 * all as-of the same moment and cannot arrive at different times disagreeing.
 */
export function postAnalysis(body: AnalysisRequest): Promise<AnalysisResponse> {
  return request<AnalysisResponse>("/analyse", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function getPresets(): Promise<PresetResponse> {
  return request<PresetResponse>("/presets");
}

/**
 * The Legs a Preset builds, as **requests** rather than as an analysis.
 *
 * They go back through `/analyse` exactly as hand-picked Legs do, which is what makes
 * "analysing a Preset" and "picking its Legs off the Chain" one operation instead of two
 * paths that agree.
 */
export async function buildPreset(name: string, moment: string): Promise<LegRequest[]> {
  const body = await request<PresetResponse>(
    `/presets/${encodeURIComponent(name)}?moment=${encodeURIComponent(moment)}`,
  );
  return body.legs ?? [];
}

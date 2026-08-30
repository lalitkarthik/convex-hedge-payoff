import { afterEach, describe, expect, mock, test } from "bun:test";

import { ApiError, apiBase, getChain, getSession, postAnalysis } from "./api";

/**
 * The client, and the two things about it that are easy to get wrong.
 *
 * **The base URL differs by where the code runs.** A server component has no origin, so
 * a relative `/api/...` resolves to nothing; the browser must stay same-origin so the
 * rewrite handles it and no CORS policy is ever needed (#25). One function decides, and
 * it is tested rather than assumed, because the failure only appears in production
 * rendering and not in the browser.
 *
 * **A failed request throws.** Returning `undefined` on a non-200 puts the error three
 * screens from its cause: the fetch succeeds, the page renders, and a chart is blank
 * with nothing in the console to say why.
 */

const ORIGINAL_FETCH = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = ORIGINAL_FETCH;
});

function respondWith(status: number, body: unknown) {
  const calls: string[] = [];
  globalThis.fetch = mock(async (input: RequestInfo | URL) => {
    calls.push(String(input));
    return new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    });
  }) as unknown as typeof fetch;
  return calls;
}

describe("where the request goes", () => {
  test("the browser stays same-origin, so the rewrite handles it and CORS never does", () => {
    expect(apiBase({ onServer: false })).toBe("/api");
  });

  test("the server uses an absolute origin, because it has none of its own", () => {
    expect(apiBase({ onServer: true, backendOrigin: "http://127.0.0.1:8000" })).toBe(
      "http://127.0.0.1:8000",
    );
  });

  test("the server falls back to localhost rather than to a relative path", () => {
    // A relative path on the server resolves to nothing and fails at render time with
    // "Failed to parse URL", which reads like a bug in Next rather than a missing var.
    expect(apiBase({ onServer: true, backendOrigin: undefined })).toMatch(/^https?:\/\//);
  });
});

describe("a request that fails", () => {
  test("throws rather than returning undefined", async () => {
    respondWith(500, { detail: "boom" });
    expect(getSession()).rejects.toBeInstanceOf(ApiError);
  });

  test("carries the status and the endpoint, so the console names the cause", async () => {
    respondWith(404, { detail: "no such preset" });
    try {
      await getChain("2026-01-27T06:30:00");
      throw new Error("should have thrown");
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      expect((error as ApiError).status).toBe(404);
      expect((error as ApiError).message).toContain("/chain");
    }
  });

  test("surfaces the server's own detail, which #31 will formalise", async () => {
    respondWith(404, { detail: "unknown preset: butterfly" });
    try {
      await getChain("2026-01-27T06:30:00");
    } catch (error) {
      expect((error as ApiError).message).toContain("unknown preset: butterfly");
    }
  });
});

describe("the requests themselves", () => {
  test("a chain asks for one moment, encoded", async () => {
    const calls = respondWith(200, { moment: "2026-01-27T06:30:00", rows: [] });
    await getChain("2026-01-27T06:30:00");
    expect(calls[0]).toContain("/chain?moment=2026-01-27T06%3A30%3A00");
  });

  test("a chain names the date and the Expiry when the view has them", async () => {
    // #68: the two dropdowns are the URL, and the URL is what the request carries. A
    // date left off would serve whichever day the moment implies - which is the same
    // day, until it is not, and nothing on screen would say which was being read.
    const calls = respondWith(200, { moment: "2026-01-07T06:30:00", rows: [] });
    await getChain("2026-01-07T06:30:00", "2026-01-07", "10FEB26");

    const asked = new URLSearchParams(calls[0].split("?")[1]);
    expect(asked.get("moment")).toBe("2026-01-07T06:30:00");
    expect(asked.get("date")).toBe("2026-01-07");
    expect(asked.get("expiry")).toBe("10FEB26");
  });

  test("a session asks for a pair and omits what it was not given", async () => {
    // Omitted rather than sent empty: `/session` reads an absent date as "open on the
    // anchor", and `?date=` would be a date it has to fail to parse.
    const calls = respondWith(200, { moments: [] });
    await getSession();
    expect(calls[0]).toEndWith("/session");

    await getSession("2026-02-10");
    expect(calls[1]).toContain("/session?date=2026-02-10");
    expect(calls[1]).not.toContain("expiry");
  });

  test("an analysis is a POST carrying the moment and the Legs together", async () => {
    // One fat request, one fat response (#23). The client never asks for the curve and
    // the metrics separately - they would arrive at different times and disagree.
    let sent: RequestInit | undefined;
    globalThis.fetch = mock(async (_input: RequestInfo | URL, init?: RequestInit) => {
      sent = init;
      return new Response(JSON.stringify({ curve: {}, metrics: {} }), { status: 200 });
    }) as unknown as typeof fetch;

    await postAnalysis({
      moment: "2026-01-27T06:30:00",
      // The Expiry is required and lives on the Leg (#71): a strike and a side name two
      // different instruments once two series trade. This case was written before that
      // landed and the typechecker could not see the file to say so.
      legs: [
        { strike: 25200, option_type: "CE", expiry: "10FEB26", direction: -1, quantity: 1 },
      ],
    });

    expect(sent?.method).toBe("POST");
    const body = JSON.parse(String(sent?.body));
    expect(body.moment).toBe("2026-01-27T06:30:00");
    expect(body.legs).toHaveLength(1);
  });

  test("an empty Strategy is still sent, because no Legs is a legitimate state", async () => {
    // It is what `/analyse` opens in before anything is picked, and the server answers
    // it with a flat zero curve rather than an error.
    const calls = respondWith(200, { curve: {}, metrics: {} });
    await postAnalysis({ moment: "2026-01-27T06:30:00", legs: [] });
    expect(calls).toHaveLength(1);
  });
});

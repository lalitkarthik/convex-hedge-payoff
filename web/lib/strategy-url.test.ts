import { describe, expect, test } from "bun:test";

import { ANCHOR, pickMoment, pickView, strategyHref } from "./strategy-url";
import type { SessionResponse } from "./types";

/**
 * What a link means, now that it addresses a **view** rather than a minute (#68).
 *
 * Three claims are graded here, and each of them is a way the two dropdowns could look
 * like they worked while quietly doing something else:
 *
 *  - **The engine resolves the pair, not the client.** `pickView` reads `session.date`
 *    and `session.expiry`, which are what the store holds. A client that echoed its own
 *    request back would render a dropdown showing a selection that is not in its own
 *    list, and a Chain that is empty underneath it.
 *  - **Changing the date moves the moment with it.** `2026-01-27T06:30:00` is not a
 *    minute of 7 January, and a moment the session does not have 500s out of `/chain`.
 *  - **A link carries all three.** A link that omitted the date would mean "whatever day
 *    the engine opens on", which is a different thing from the day the sender saw.
 *
 * The sessions below are fixtures of the *shape* the endpoint publishes, not of its
 * answers - the answers are graded over HTTP in `tests/test_api_session.py`, where they
 * are checked against what `/chain` will actually serve.
 */

function session(over: Partial<SessionResponse> = {}): SessionResponse {
  const moments = ["2026-01-27T03:45:00", ANCHOR, "2026-01-27T10:00:00"];
  return {
    date: "2026-01-27",
    dates: ["2026-01-07", "2026-01-27", "2026-02-10"],
    moments,
    moment_count: moments.length,
    first_moment: moments[0],
    last_moment: moments[moments.length - 1],
    expiry: "10FEB26",
    expiries: ["10FEB26"],
    strike_min: 23300,
    strike_max: 27950,
    presets: ["straddle"],
    ...over,
  };
}

describe("the moment, when the day underneath it changes", () => {
  test("a minute this session has is the minute rendered", () => {
    expect(pickMoment(session(), "2026-01-27T10:00:00")).toBe("2026-01-27T10:00:00");
  });

  test("the same clock time is kept on the day that was picked", () => {
    // The trader was reading 12:00 IST on the anchor and clicked 7 January. Landing at
    // 12:00 on the 7th continues what they were doing; landing at the open answers a
    // different question.
    const seventh = session({
      date: "2026-01-07",
      moments: ["2026-01-07T03:45:00", "2026-01-07T06:30:00", "2026-01-07T09:59:00"],
    });

    expect(pickMoment(seventh, ANCHOR)).toBe("2026-01-07T06:30:00");
  });

  test("a clock time the new day never quoted falls back rather than 500ing", () => {
    // The sparse days are full of gaps - 7 January quoted 150 of the session's 376
    // minutes - so this is the ordinary case there, not the edge.
    const thin = session({
      date: "2026-01-07",
      moments: ["2026-01-07T08:14:00", "2026-01-07T09:59:00"],
    });

    expect(thin.moments).toContain(pickMoment(thin, ANCHOR));
  });

  test("a hand-edited moment falls back to the anchor where the session has it", () => {
    expect(pickMoment(session(), "not-a-moment")).toBe(ANCHOR);
    expect(pickMoment(session(), undefined)).toBe(ANCHOR);
  });

  test("the clock is matched whole, so 06:30 cannot be answered with 16:30", () => {
    // The stamps are fixed-width ISO 8601 and the tail is compared as text, which is
    // only safe because the `T` is part of what is compared.
    const day = session({
      date: "2026-02-10",
      moments: ["2026-02-10T03:45:00", "2026-02-10T10:00:00"],
    });

    expect(pickMoment(day, "2026-01-27T06:30:00")).toBe("2026-02-10T03:45:00");
  });
});

describe("the view a page renders", () => {
  test("is the pair the engine resolved, never the pair the link asked for", () => {
    // The session was asked for something; this is what came back. The client has no
    // way to know which pairs exist and must not pretend otherwise.
    const resolved = session({ date: "2026-01-07", expiry: "10FEB26" });

    expect(pickView(resolved, ANCHOR).date).toBe("2026-01-07");
    expect(pickView(resolved, ANCHOR).expiry).toBe("10FEB26");
  });

  test("carries a moment the session actually has, whatever the link held", () => {
    const view = pickView(session(), "2099-01-01T00:00:00");
    expect(session().moments).toContain(view.moment);
  });
});

describe("the link a copy produces", () => {
  test("carries the date, the Expiry and the moment, every time", () => {
    const href = strategyHref("/", pickView(session(), ANCHOR), []);

    const params = new URLSearchParams(href.slice(href.indexOf("?")));
    expect(params.get("date")).toBe("2026-01-27");
    expect(params.get("expiry")).toBe("10FEB26");
    expect(params.get("moment")).toBe(ANCHOR);
    expect(params.get("legs")).toBeNull();
  });

  test("reopens the same view: what it writes is what the pages read back", () => {
    // The round trip is the acceptance criterion - "both selections are carried in the
    // URL and restore on reload" - and it is a round trip only if the parameter names
    // the pages read are the ones this writes.
    const before = pickView(session({ date: "2026-02-10", expiry: "10FEB26" }), ANCHOR);
    const params = new URLSearchParams(strategyHref("/analyse", before, []).split("?")[1]);

    expect(params.get("date")).toBe(before.date);
    expect(params.get("expiry")).toBe(before.expiry);
    expect(params.get("moment")).toBe(before.moment);
  });

  test("puts the Legs alongside the view rather than in place of it", () => {
    const href = strategyHref("/analyse", pickView(session(), ANCHOR), [
      {
        strike: 25200,
        option_type: "CE",
        expiry: "10FEB26",
        direction: -1,
        quantity: 1,
        entry_premium: 344.05,
      },
    ]);

    expect(href.startsWith("/analyse?")).toBe(true);
    const params = new URLSearchParams(href.split("?")[1]);
    expect(params.get("legs")).toBe("25200CE10FEB26S1@344.05");
    expect(params.get("date")).toBe("2026-01-27");
  });
});

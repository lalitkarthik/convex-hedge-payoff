import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { chromium, type Browser, type Page } from "playwright-core";

/**
 * The only test that proves the two halves are actually joined.
 *
 * Everything else in this repo grades one side: `pytest` grades the engine, `bun test`
 * grades the codec and the client in isolation, `tsc` grades the shapes. None of them
 * would notice if the rewrite were misconfigured, the moment format disagreed, or
 * `/analyse` returned a field the page reads under another name — the build would pass
 * and the chart would be blank.
 *
 * So this drives a real browser against a real Next server against a real uvicorn, and
 * asserts the figures a trader reads. It needs both running:
 *
 *     .venv/bin/python -m uvicorn payoff.api:app --port 8000
 *     cd web && bun run dev
 *     E2E=1 bun test e2e/
 *
 * Skipped unless `E2E=1`, so `bun test` stays a unit run that needs no servers.
 *
 * The figures below are the engine's own, asserted elsewhere in `tests/`. Repeating them
 * here is the point: if the page shows different numbers from the API, one of the two
 * layers between them is lying.
 */

const RUN = process.env.E2E === "1";
const BASE = process.env.E2E_BASE ?? "http://localhost:3000";
const ANCHOR = "2026-01-27T06:30:00";

// Left unset in CI, where `playwright install` puts chromium where playwright-core
// looks for it. Set locally, because this machine's browser was assembled by hand.
const CHROME = process.env.CHROME;

const STRADDLE = "25200CE10FEB26S1@344.05,25200PE10FEB26S1@326.7";

let browser: Browser;
let page: Page;
const consoleErrors: string[] = [];

beforeAll(async () => {
  if (!RUN) return;
  browser = await chromium.launch({
    ...(CHROME ? { executablePath: CHROME } : {}),
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });
  page = await browser.newPage({ viewport: { width: 1600, height: 950 } });
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(String(error)));
});

afterAll(async () => {
  await browser?.close();
});

const it = RUN ? test : test.skip;

describe("the Chain page", () => {
  it("renders the anchor minute's chain from the live engine", async () => {
    await page.goto(`${BASE}/?moment=${encodeURIComponent(ANCHOR)}`, {
      waitUntil: "networkidle",
    });

    // 91 strikes at this minute, served as-of. A chain of nine means the strict slice
    // is being rendered instead; a chain of zero means the backend is not reachable.
    expect(await page.locator("table.chain tbody tr").count()).toBe(91);

    const header = await page.locator(".header").innerText();
    expect(header).toContain("25,100.25"); // spot
    expect(header).toContain("25,219.12"); // forward, fitted by parity
    expect(header).toContain("118.87"); //   the basis, why the star is not on spot
    expect(header).toContain("10FEB26");
  });

  it("stars the strike nearest the forward, not the one nearest spot", async () => {
    // 25,200 against the 25,100 that spot would pick. The basis is more than two strike
    // intervals wide, so the two genuinely disagree and this is a decision, not rounding.
    const starred = await page.locator("tr.at-the-money td.strike").innerText();
    expect(starred).toContain("25,200");
  });

  it("puts a picked Leg in the address bar, where it survives a reload", async () => {
    await page.locator("tr.at-the-money .bs button.sell").first().click();
    await page.waitForFunction(() => window.location.search.includes("legs="));

    expect(decodeURIComponent(page.url())).toContain("25200CE10FEB26S1@344.05");

    await page.reload({ waitUntil: "networkidle" });
    expect(await page.locator(".legs .leg").count()).toBe(1);
  });
});

describe("the Analyse page", () => {

  it("reproduces the whole Strategy from a cold URL", async () => {
    // The heart of #32: no click path, no store, no session - just the link. This is the
    // page a reviewer opens instead of reading a diff of chart code.
    await page.goto(
      `${BASE}/analyse?moment=${encodeURIComponent(ANCHOR)}&legs=${encodeURIComponent(STRADDLE)}`,
      { waitUntil: "networkidle" },
    );

    expect(await page.locator(".legs .leg").count()).toBe(2);
    await page.waitForSelector("svg.recharts-surface");
  });

  it("shows the short straddle's published metrics", async () => {
    const metrics = await page.locator("table.kv").innerText();

    expect(metrics).toContain("670.75"); //    max profit, the premium received
    expect(metrics).toContain("Unlimited"); // max loss, never an infinity token
    expect(metrics).toContain("24,529.25");
    expect(metrics).toContain("25,870.75");
  });

  it("shows per-Leg Greeks the client did not compute", async () => {
    await page.getByRole("tab", { name: "Greeks" }).click();
    const greeks = await page.locator("table.grid").innerText();

    expect(greeks).toContain("25,200 CE");
    expect(greeks).toContain("25,200 PE");
    expect(greeks).toContain("Total");
  });

  it("shows a payoff table whose peak row is the strike", async () => {
    await page.getByRole("tab", { name: "Payoff Table" }).click();
    const rows = await page.locator("table.grid tbody tr").allInnerTexts();

    const peak = rows.find((row) => row.includes("25,200"));
    expect(peak).toBeDefined();
    expect(peak).toContain("670.75");
  });

  it("labels both axes Forward, because that is what they plot", async () => {
    // #72: the wire stopped calling these numbers `spot`, so the screen has to stop too.
    // A renamed field under a stale label fixes nothing for whoever is reading the chart,
    // and the label is the only place the unit is visible: 25,200 is a plausible Spot and
    // an equally plausible Forward, and the two are 118.87 apart at this minute.
    //
    // The Payoff Table tab is the one the test above left open.
    // innerText returns text as rendered, and the header is uppercased in CSS, so this
    // compares case-insensitively: the assertion is about the word, not the styling.
    const heading = await page.locator("table.grid thead").innerText();
    expect(heading.toLowerCase()).toContain("forward at expiry");
    expect(heading.toLowerCase()).not.toContain("spot");

    // The chart sits above the tabs and is rendered whichever one is selected.
    const chart = await page.locator("svg.recharts-surface").textContent();
    expect(chart).toContain("Forward at expiry");
  });

  it("refuses a link it cannot read, rather than analysing part of one", async () => {
    // Nine legs truncated to eight and a half by a chat client is the realistic case.
    // A chart of the eight that parsed would be wrong with nothing on screen saying so.
    await page.goto(`${BASE}/analyse?moment=${encodeURIComponent(ANCHOR)}&legs=25200CE10FEB26S1,garbage`, {
      waitUntil: "networkidle",
    });

    expect(await page.locator(".problem").count()).toBe(1);
    expect(await page.locator("svg.recharts-surface").count()).toBe(0);
  });
});

describe("the strike slider", () => {
  it("offers only the strikes this minute quotes on this Leg's side", async () => {
    await page.goto(
      `${BASE}/analyse?moment=${encodeURIComponent(ANCHOR)}&legs=${encodeURIComponent(STRADDLE)}`,
      { waitUntil: "networkidle" },
    );

    // 68 of the anchor's 91 strikes quote a call *and* carry a volatility - the two
    // conditions the engine applies. The day's grid is 94 and the minute's chain is 91,
    // so a slider reading either would stop on strikes that cannot be priced.
    const slider = page.locator(".strike-slider input[type=range]");
    expect(await slider.getAttribute("max")).toBe("67");
    expect(await page.locator(".strike-slider .time-ends").innerText()).toContain("68 quoted");

    // It opens on the first Leg, pointed at the strike that Leg actually holds.
    expect(await page.locator(".strike-slider .strike-now").innerText()).toContain("25,200");
  });

  it("moves the Leg, and drops the Entry Premium so the engine reprices", async () => {
    // The correctness assertion of this feature. `entry_premium` is optional on the
    // wire and absent means "read the Chain's last". Carried, 344.05 would be honoured
    // at the new strike and the published Breakeven would be wrong with nothing saying so.
    await page.locator(".strike-slider input[type=range]").focus();
    await page.keyboard.press("ArrowRight");
    await page.waitForFunction(() => window.location.search.includes("25250CE"));

    const url = decodeURIComponent(page.url());
    expect(url).toContain("25250CE10FEB26S1");
    expect(url).not.toContain("25250CE10FEB26S1@"); // the premium is gone, not zeroed
    expect(url).toContain("25200PE10FEB26S1@326.7"); // the Leg not moved keeps its own

    // A different Strategy, so different figures. The short straddle's published 670.75
    // belongs to two Legs at one strike; this is a strangle, and its premium is the
    // 25,250 call's own last (317.75) plus the put's 326.70. If 344.05 had been carried
    // across, this would read 670.75 still and look untouched.
    const metrics = await page.locator("table.kv").innerText();
    expect(metrics).toContain("644.45");
    expect(metrics).toContain("24,555.55"); // 25,200 - 644.45
    expect(metrics).toContain("25,894.45"); // 25,250 + 644.45

    // And the panel must not fill the empty premium with a 0, which would read as a
    // position entered for nothing rather than one priced off the Chain.
    const premiums = await page.locator('.legs input[aria-label="entry premium"]').all();
    expect(await premiums[0]!.inputValue()).toBe("");
    expect(await premiums[1]!.inputValue()).toBe("326.7");
  });

  it("reproduces the moved Strategy from the URL alone", async () => {
    // Same property #32 exists for, now that a second control writes the address bar.
    const moved = page.url();
    await page.goto(moved, { waitUntil: "networkidle" });

    expect(await page.locator(".legs .leg").count()).toBe(2);
    expect(await page.locator(".strike-slider .strike-now").innerText()).toContain("25,250");
  });

  it("points at whichever Leg the trader picks", async () => {
    // The put's ladder is not the call's - 64 strikes against 68 at this minute - so
    // selecting the other Leg has to rebuild it, not just move the thumb.
    await page.locator(".legs .leg").nth(1).click();

    expect(await page.locator(".strike-slider .strike-now").innerText()).toContain("PE");
    expect(await page.locator(".strike-slider .time-ends").innerText()).toContain("64 quoted");
  });
});

describe("the theme", () => {
  it("wears the dark palette when the machine asks for one", async () => {
    // The palette is 18 custom properties on `:root`, and every component but the chart
    // carries no colour of its own - so one token read is a fair proxy for all of them.
    // What this actually guards is the cascade: the dark rules live behind
    // `:root:not([data-theme="light"])`, and a selector typo there fails open to light
    // with nothing else on screen looking wrong.
    const dark = await browser.newPage({ colorScheme: "dark" });
    await dark.goto(`${BASE}/?moment=${encodeURIComponent(ANCHOR)}`, { waitUntil: "networkidle" });

    const background = await dark.evaluate(() => getComputedStyle(document.body).backgroundColor);
    expect(background).toBe("rgb(14, 19, 25)"); // --bg dark, #0e1319

    await dark.close();
  });

  it("lets a trader on a light machine choose dark anyway", async () => {
    // The half a media query cannot do. `data-theme="dark"` has to beat a light system,
    // which is why the palette is declared a third time rather than only in the query.
    const light = await browser.newPage({ colorScheme: "light" });
    await light.goto(`${BASE}/?moment=${encodeURIComponent(ANCHOR)}`, { waitUntil: "networkidle" });

    expect(await light.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe(
      "rgb(246, 247, 249)", // --bg light, #f6f7f9
    );

    // Auto -> Light -> Dark: two presses from the default.
    await light.locator("button.theme").click();
    await light.locator("button.theme").click();

    expect(await light.evaluate(() => document.documentElement.dataset.theme)).toBe("dark");
    expect(await light.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe(
      "rgb(14, 19, 25)",
    );

    // The choice is what survives a reload, not the attribute - the inline script in
    // `layout.tsx` has to put it back before the first paint.
    await light.reload({ waitUntil: "networkidle" });
    expect(await light.evaluate(() => document.documentElement.dataset.theme)).toBe("dark");

    await light.close();
  });

  it("draws the P&L curve in ink that is not the background", async () => {
    // Recharts takes colour as JS props, so these never touch the cascade; they were
    // twelve hex literals copied from `:root` and would have stayed light. A stroke that
    // resolves to nothing is the specific failure - `var(--nonsense)` renders as none.
    const dark = await browser.newPage({ colorScheme: "dark" });
    await dark.goto(
      `${BASE}/analyse?moment=${encodeURIComponent(ANCHOR)}&legs=${encodeURIComponent(STRADDLE)}`,
      { waitUntil: "networkidle" },
    );
    await dark.waitForSelector("svg.recharts-surface");

    const stroke = await dark.evaluate(() => {
      const curve = document.querySelector("svg.recharts-surface .recharts-area-curve");
      return curve ? getComputedStyle(curve).stroke : null;
    });
    expect(stroke).toBe("rgb(230, 237, 243)"); // --ink dark, #e6edf3

    await dark.close();
  });
});

describe("the console", () => {
  it("is clean", () => {
    // A page that renders correctly while throwing is a page that will stop rendering
    // correctly on the next change.
    expect(consoleErrors).toEqual([]);
  });
});

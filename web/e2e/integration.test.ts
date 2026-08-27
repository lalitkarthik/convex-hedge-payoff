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
  const STRADDLE = "25200CE10FEB26S1@344.05,25200PE10FEB26S1@326.7";

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
    const heading = await page.locator("table.grid thead").innerText();
    expect(heading).toContain("Forward at expiry");
    expect(heading).not.toContain("Spot");

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

describe("the console", () => {
  it("is clean", () => {
    // A page that renders correctly while throwing is a page that will stop rendering
    // correctly on the next change.
    expect(consoleErrors).toEqual([]);
  });
});

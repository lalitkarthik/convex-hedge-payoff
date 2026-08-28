import { describe, expect, test } from "bun:test";

import { type Theme, nextTheme, readTheme, themeAttribute } from "./theme";

/**
 * The theme is read from `localStorage` before the bundle runs, so the one property
 * that matters is that **nothing a browser can hand back leaves the app themeless**.
 * Storage is shared, editable from the console, and survives deploys that change what
 * the values mean; a stray entry must degrade to following the operating system rather
 * than to an unstyled page.
 */

describe("readTheme", () => {
  test("the three real settings map to themselves", () => {
    expect(readTheme("auto")).toBe("auto");
    expect(readTheme("light")).toBe("light");
    expect(readTheme("dark")).toBe("dark");
  });

  test("a browser with nothing stored follows the operating system", () => {
    expect(readTheme(null)).toBe("auto");
  });

  test("anything else is not trusted, and follows the operating system", () => {
    // Case matters: the writer only ever stores lowercase, so a capitalised value did
    // not come from this app and is not evidence of what the trader chose.
    for (const stored of ["", "DARK", "Light", "purple", "[object Object]", "null", " dark "]) {
      expect(readTheme(stored)).toBe("auto");
    }
  });
});

describe("nextTheme", () => {
  test("the toggle cycles auto to light to dark and back", () => {
    expect(nextTheme("auto")).toBe("light");
    expect(nextTheme("light")).toBe("dark");
    expect(nextTheme("dark")).toBe("auto");
  });

  test("cycling three times from any setting returns to it", () => {
    // One control with three states, so the trader must be able to reach every one of
    // them and get back without reloading. A cycle that lost `auto` would strand
    // anyone who had left it - they could never return to following the system.
    for (const start of ["auto", "light", "dark"] as Theme[]) {
      expect(nextTheme(nextTheme(nextTheme(start)))).toBe(start);
    }
  });
});

describe("themeAttribute", () => {
  test("an explicit choice names itself, and wins over the media query", () => {
    expect(themeAttribute("dark")).toBe("dark");
    expect(themeAttribute("light")).toBe("light");
  });

  test("auto sets no attribute at all", () => {
    // Null means *remove* it, and that is the whole mechanism: the dark rules are
    // written as `@media (prefers-color-scheme: dark) :root:not([data-theme="light"])`,
    // so leaving the attribute behind - even set to "auto" - would keep overriding the
    // system rather than deferring to it.
    expect(themeAttribute("auto")).toBeNull();
  });
});

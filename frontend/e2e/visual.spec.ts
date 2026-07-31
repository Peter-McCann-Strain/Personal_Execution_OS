import { expect, test } from "@playwright/test";
import { installCriticalPathMocks } from "./helpers/critical-path-mocks";
import { maskDynamicRegions, setTheme, type UITheme } from "./helpers/theme";

/** 7 routes x 2 themes = 14 baseline screenshots. */
const SNAPSHOT_ROUTES = [
  "/dashboard",
  "/chat",
  "/memory",
  "/diary",
  "/monitoring",
  "/settings",
  "/pulse",
] as const;

const THEMES: UITheme[] = ["dark", "light"];

test.describe("Visual regression", () => {
  test.beforeEach(async ({ page }) => {
    // Seed api_key so protected routes render rather than redirecting.
    await page.addInitScript(() => {
      try {
        sessionStorage.setItem("api_key", "e2e-visual-test-key");
      } catch {
        // ignore
      }
    });
    await installCriticalPathMocks(page);
  });

  for (const theme of THEMES) {
    for (const route of SNAPSHOT_ROUTES) {
      const filename = `${route.replace(/^\//, "").replace(/\//g, "-") || "root"}-${theme}.png`;

      test(`${route} @ ${theme}`, async ({ page }) => {
        await setTheme(page, theme);
        await page.goto(route);
        await page.waitForLoadState("networkidle", { timeout: 5_000 }).catch(() => undefined);
        await maskDynamicRegions(page);

        const screenshot = await page.screenshot({
          fullPage: true,
          animations: "disabled",
          caret: "hide",
        });

        expect(screenshot).toMatchSnapshot(filename, {
          threshold: 0.02,
          maxDiffPixelRatio: 0.02,
        });
      });
    }
  }
});

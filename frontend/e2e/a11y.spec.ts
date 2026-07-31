import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { EXCLUDE_SELECTORS, GLOBAL_DISABLED_RULES } from "./a11y-config";
import { installCriticalPathMocks } from "./helpers/critical-path-mocks";

/**
 * Seed the api_key so auth-guarded routes don't redirect to /setup
 * before the AxeBuilder scan runs.
 */
async function seedApiKey(page: import("@playwright/test").Page) {
  await page.addInitScript(() => {
    try {
      sessionStorage.setItem("api_key", "e2e-axe-test-key");
    } catch {
      // addInitScript may run in a context without sessionStorage; ignore.
    }
  });
}

const MAIN_ROUTES = [
  "/setup",
  "/dashboard",
  "/chat",
  "/memory",
  "/diary",
  "/workbench",
  "/projects",
  "/goals",
  "/monitoring",
  "/settings",
] as const;

test.describe("WCAG 2.1 AA accessibility audit", () => {
  test.beforeEach(async ({ page }) => {
    await seedApiKey(page);
    await installCriticalPathMocks(page);
  });

  for (const route of MAIN_ROUTES) {
    test(`has no WCAG 2.1 AA violations on ${route}`, async ({ page }) => {
      await page.goto(route);
      // Let lazy routes settle before scanning.
      await page.waitForLoadState("networkidle", { timeout: 5_000 }).catch(() => undefined);

      let builder = new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]);

      if (GLOBAL_DISABLED_RULES.length > 0) {
        builder = builder.disableRules(GLOBAL_DISABLED_RULES);
      }
      for (const selector of EXCLUDE_SELECTORS) {
        builder = builder.exclude(selector);
      }

      const results = await builder.analyze();
      expect(results.violations).toEqual([]);
    });
  }
});

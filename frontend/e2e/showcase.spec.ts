import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { installCriticalPathMocks } from "./helpers/critical-path-mocks";

const repositoryRoot = fileURLToPath(new URL("../..", import.meta.url));

test.skip(
  process.env.CAPTURE_SHOWCASE !== "1",
  "Run `npm run capture:showcase` to refresh public sample screenshots.",
);

test("captures the fixture-only mobile dashboard", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await installCriticalPathMocks(page);
  await page.goto("/dashboard");
  await page.waitForLoadState("networkidle", { timeout: 5_000 }).catch(() => undefined);
  await page.evaluate(() => document.fonts.ready);

  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await page.screenshot({
    path: `${repositoryRoot}/docs/assets/product-mobile.png`,
    fullPage: true,
    animations: "disabled",
  });
});

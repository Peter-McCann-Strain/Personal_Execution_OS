import { fileURLToPath } from "node:url";
import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";
import { installCriticalPathMocks } from "./helpers/critical-path-mocks";

const repositoryRoot = fileURLToPath(new URL("../..", import.meta.url));

test.skip(
  process.env.CAPTURE_SHOWCASE !== "1",
  "Run `npm run capture:showcase` to refresh public sample screenshots.",
);

async function captureDashboard(
  page: Page,
  {
    width,
    height,
    filename,
  }: {
    width: number;
    height: number;
    filename: string;
  },
) {
  await page.setViewportSize({ width, height });
  await installCriticalPathMocks(page);
  await page.goto("/dashboard");
  await page.waitForLoadState("networkidle", { timeout: 5_000 }).catch(() => undefined);
  await page.evaluate(() => document.fonts.ready);

  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await page.screenshot({
    path: `${repositoryRoot}/docs/assets/${filename}`,
    fullPage: true,
    animations: "disabled",
  });
}

test("captures the fixture-only desktop dashboard", async ({ page }) => {
  await captureDashboard(page, {
    width: 1440,
    height: 1080,
    filename: "product-overview.png",
  });
});

test("captures the fixture-only mobile dashboard", async ({ page }) => {
  await captureDashboard(page, {
    width: 390,
    height: 844,
    filename: "product-mobile.png",
  });
});

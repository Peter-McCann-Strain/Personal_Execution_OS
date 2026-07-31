import { expect, test } from "@playwright/test";
import { installCriticalPathMocks } from "./helpers/critical-path-mocks";

test.beforeEach(async ({ page }) => {
  await installCriticalPathMocks(page);
});

test("today cockpit shows commitments and read-only calendar context", async ({ page }) => {
  await page.goto("/dashboard");

  await expect(page.getByRole("heading", { name: "Today" })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Reply to Maria about the design review" }),
  ).toBeVisible();

  await expect(page.getByRole("button", { name: "Schedule" })).toHaveCount(0);
  await expect(page.getByText("Planning review")).toBeVisible();
});

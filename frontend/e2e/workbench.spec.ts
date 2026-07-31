import { expect, test } from "@playwright/test";
import { installCriticalPathMocks } from "./helpers/critical-path-mocks";

test.beforeEach(async ({ page }) => {
  await installCriticalPathMocks(page);
});

test("workbench saved views expose backend records as list, board, and filtered results", async ({
  page,
}) => {
  await page.goto("/workbench");

  await expect(page.getByRole("heading", { name: "Workbench" })).toBeVisible();
  await expect(page.getByText("Send the revised launch brief")).toBeVisible();
  await expect(page.getByText("Planning review")).toBeVisible();
  await expect(page.getByText("Evening review")).toBeVisible();

  const launchRow = page
    .getByRole("heading", { name: "Send the revised launch brief" })
    .locator("xpath=ancestor::div[contains(@class, 'border-b')][1]");
  await expect(launchRow.getByRole("button", { name: "Schedule" })).toHaveCount(0);
  await expect(page.getByText("Planning review")).toBeVisible();

  await page.getByRole("button", { name: /At Risk/ }).click();
  await expect(page.getByText("Rebuild the personal operating system")).toBeVisible();
  await expect(page.getByText("Reply to Maria about the design review")).toBeVisible();

  await page.getByRole("tab", { name: "Board" }).click();
  await expect(page.getByRole("heading", { name: "Overdue" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Waiting" })).toBeVisible();

  await page.getByPlaceholder("Filter this view...").fill("Maria");
  await expect(page.getByText("Reply to Maria about the design review")).toBeVisible();
  await expect(page.getByText("Rebuild the personal operating system")).toBeHidden();
});

test("workbench remains usable on a mobile viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/workbench");

  await expect(page.getByRole("heading", { name: "Workbench" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Saved Views" })).toBeVisible();

  await page.getByText("Projects and next actions from nested tasks.").click();
  await expect(
    page.getByRole("heading", { name: "Assistant frontend quality pass" }),
  ).toBeVisible();

  await page.getByRole("tab", { name: "Timeline" }).click();
  await expect(page.getByText("Add saved view filtering")).toBeVisible();

  await page.getByPlaceholder("Filter this view...").fill("frontend");
  await expect(page.getByText("Assistant frontend quality pass")).toBeVisible();
});

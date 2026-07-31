import { expect, test } from "@playwright/test";
import { installCriticalPathMocks } from "./helpers/critical-path-mocks";

test.beforeEach(async ({ page }) => {
  await installCriticalPathMocks(page);
});

test("app shell exposes the primary navigation and routes cleanly", async ({ page }) => {
  await page.goto("/dashboard");

  await expect(page).toHaveTitle("Dashboard — Execution OS");
  await expect(page.getByRole("button", { name: "Toggle sidebar" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Chat" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Monitoring" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Settings" })).toBeVisible();

  await page.getByRole("button", { name: "Chat" }).click();
  await expect(page).toHaveURL(/\/chat$/);
  await expect(page.getByText("How can I help?")).toBeVisible();

  await page.getByRole("button", { name: "Monitoring" }).click();
  await expect(page).toHaveURL(/\/monitoring$/);
  await expect(page.getByRole("heading", { name: "System Monitoring" })).toBeVisible();
});

test("chat streams a response and renders the active agent", async ({ page }) => {
  await page.goto("/chat");

  await expect(page.getByText("How can I help?")).toBeVisible();
  await page.getByPlaceholder("Ask anything...").fill("Summarize the current priorities.");
  await page.getByRole("button", { name: "Send message" }).click();

  await expect(page.getByText("Summarize the current priorities.")).toBeVisible();
  await expect(page.getByText("Here is a concise plan.")).toBeVisible();
  await expect(page.locator("span.capitalize").filter({ hasText: "communications" })).toBeVisible();
  await expect(page.getByText("calendar.lookup")).toBeVisible();
});

test("dashboard and monitoring readiness surfaces load without backend services", async ({
  page,
}) => {
  await page.goto("/dashboard");

  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Morning Briefing" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Goal Progress" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Quick Actions" })).toBeVisible();
  await expect(page.getByText("Today's Mood")).toBeVisible();
  await expect(page.getByText("Unread Emails")).toBeVisible();
  await expect(page.getByText("Recent Diary")).toBeVisible();
  await expect(page.getByText("Agent Activity")).toBeVisible();

  await page.getByRole("button", { name: "Monitoring" }).click();
  await expect(page).toHaveURL(/\/monitoring$/);

  await page.getByRole("tab", { name: "Readiness" }).click();
  await expect(page.getByRole("heading", { name: "Prompt Governance" })).toBeVisible();
  await expect(page.getByText("Startup Readiness")).toBeVisible();
  await expect(page.getByText("supervisor.v12")).toBeVisible();

  await page.getByRole("tab", { name: "Context" }).click();
  await expect(page.getByRole("heading", { name: "Context Inspector" })).toBeVisible();
  await page.getByRole("button", { name: "Inspect Context" }).click();
  await expect(page.getByText("Total Budget")).toBeVisible();
  await expect(page.getByText("Durable Candidates")).toBeVisible();
  await expect(page.getByText("User prefers a fast, practical execution cadence.")).toBeVisible();
});

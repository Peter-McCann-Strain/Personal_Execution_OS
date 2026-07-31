import { describe, it, expect } from "vitest";
import { readdirSync, readFileSync } from "fs";
import { resolve } from "path";
import { absolutePath, apiPath } from "@/api/client";
import { API_PATHS } from "@/api/generated/paths";

/**
 * API client structural tests — verify all API modules follow
 * consistent patterns and cover backend endpoints.
 */

const apiDir = resolve(__dirname, "../src/api");
const apiFiles = readdirSync(apiDir).filter((f) => f.endsWith(".ts") && f !== "client.ts");

describe("API Client Modules", () => {
  it("has API clients for all major features", () => {
    const expectedModules = [
      "dashboard",
      "episodes",
      "memory",
      "contacts",
      "goals",
      "projects",
      "reviews",
      "calendar",
      "email",
      "notifications",
      "monitoring",
      "notes",
      "commitments",
      "habits",
      "decisions",
      "tutorials",
    ];

    for (const mod of expectedModules) {
      expect(apiFiles).toContain(`${mod}.ts`);
    }
  });

  it("all API modules import from client.ts", () => {
    for (const file of apiFiles) {
      const content = readFileSync(resolve(apiDir, file), "utf-8");
      expect(content).toContain('from "./client"');
    }
  });

  it("feature API modules use generated contract paths instead of hard-coded routes", () => {
    for (const file of apiFiles) {
      if (file === "generated" || file === "client.ts") {
        continue;
      }

      const content = readFileSync(resolve(apiDir, file), "utf-8");
      expect(content).toContain('from "./generated/paths"');
      expect(content).not.toMatch(/["'`]\/(api\/)?[a-z0-9-]+(?:\/[a-z0-9-{}]+)+["'`]/i);
    }
  });

  it("client.ts exports ApiError and utility functions", () => {
    const clientContent = readFileSync(resolve(apiDir, "client.ts"), "utf-8");
    expect(clientContent).toContain("export");
    expect(clientContent).toContain("ApiError");
    expect(clientContent).toContain("apiPath");
    // Client should have HTTP methods (get, post, etc.)
    expect(clientContent).toMatch(/(get|post|put|patch|delete)[<(]/);
  });
});

describe("API Endpoint Coverage", () => {
  // Notes endpoints
  it("notes API covers search, CRUD, and links", () => {
    const content = readFileSync(resolve(apiDir, "notes.ts"), "utf-8");
    expect(content).toContain("searchNotes");
    expect(content).toContain("createNote");
    expect(content).toContain("getNote");
    expect(content).toContain("updateNote");
    expect(content).toContain("deleteNote");
    expect(content).toContain("getLinkedNotes");
    expect(content).toContain("createNoteLink");
  });

  // Commitments endpoints
  it("commitments API covers open, overdue, and status update", () => {
    const content = readFileSync(resolve(apiDir, "commitments.ts"), "utf-8");
    expect(content).toContain("getOpenCommitments");
    expect(content).toContain("getOverdueCommitments");
    expect(content).toContain("updateCommitmentStatus");
  });

  // Habits endpoints
  it("habits API covers list, create, complete, and logs", () => {
    const content = readFileSync(resolve(apiDir, "habits.ts"), "utf-8");
    expect(content).toContain("getHabits");
    expect(content).toContain("createHabit");
    expect(content).toContain("completeHabit");
    expect(content).toContain("getHabitLogs");
  });

  // Decisions endpoints
  it("decisions API covers list, create, due-review, and outcome", () => {
    const content = readFileSync(resolve(apiDir, "decisions.ts"), "utf-8");
    expect(content).toContain("getDecisions");
    expect(content).toContain("createDecision");
    expect(content).toContain("getDecisionsDueReview");
    expect(content).toContain("recordOutcome");
  });

  // Tutorials endpoints
  it("tutorials API covers list, start, turn, and end", () => {
    const content = readFileSync(resolve(apiDir, "tutorials.ts"), "utf-8");
    expect(content).toContain("getTutorials");
    expect(content).toContain("startTutorial");
    expect(content).toContain("sendTutorialTurn");
    expect(content).toContain("endTutorial");
  });

  it("monitoring API covers health, preflight, and prompt governance", () => {
    const content = readFileSync(resolve(apiDir, "monitoring.ts"), "utf-8");
    expect(content).toContain("getHealth");
    expect(content).toContain("getPreflightReport");
    expect(content).toContain("getPromptVersions");
    expect(content).toContain("getTraceSummaries");
    expect(content).toContain("getEvalOutcomes");
    expect(content).toContain("getChannelMetrics");
    expect(content).toContain("getTelegramWebhookStatus");
  });
});

describe("Generated path helpers", () => {
  it("apiPath strips the shared /api prefix and fills route params", () => {
    expect(apiPath(API_PATHS.apiGoalsByGoalId, { goal_id: "abc 123" })).toBe("/goals/abc%20123");
  });

  it("absolutePath preserves non-API routes for direct fetch usage", () => {
    expect(absolutePath(API_PATHS.health)).toBe("/health");
  });
});

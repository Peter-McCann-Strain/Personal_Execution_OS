import { describe, it, expect } from "vitest";
import { navSections } from "@/components/layout/sidebar.config";
import type { NavItem, NavSection } from "@/components/layout/sidebar.config";

/**
 * Structural tests for navigation data — these run without rendering
 * and ensure the nav config stays consistent.
 */
describe("Navigation Data Integrity", () => {
  const allItems = navSections.flatMap((s: NavSection) => s.items);
  const allPaths = allItems.map((item: NavItem) => item.path);

  it("has no duplicate paths", () => {
    const unique = new Set(allPaths);
    expect(unique.size).toBe(allPaths.length);
  });

  it("has no duplicate labels", () => {
    const labels = allItems.map((item: NavItem) => item.label);
    const unique = new Set(labels);
    expect(unique.size).toBe(labels.length);
  });

  it("total nav items is 21", () => {
    expect(allItems.length).toBe(21);
  });

  it("every item has a label, icon, and path", () => {
    for (const item of allItems) {
      expect(item.label).toBeTruthy();
      expect(item.icon).toBeTruthy();
      expect(item.path).toBeTruthy();
    }
  });

  it("all paths match the router routes", () => {
    const expectedPaths = [
      "/dashboard",
      "/chat",
      "/diary",
      "/memory",
      "/knowledge-graph",
      "/notes",
      "/workbench",
      "/projects",
      "/pulse",
      "/goals",
      "/reviews",
      "/habits",
      "/commitments",
      "/decisions",
      "/contacts",
      "/calendar",
      "/email",
      "/tutorials",
      "/notifications",
      "/monitoring",
      "/settings",
    ];
    expect(allPaths.sort()).toEqual(expectedPaths.sort());
  });

  it("agent colors are only valid agent names", () => {
    const validAgents = [
      "diary",
      "memory",
      "research",
      "review",
      "project",
      "communications",
      "tools",
      "notification",
    ];
    for (const item of allItems) {
      if (item.agentColor) {
        expect(validAgents).toContain(item.agentColor);
      }
    }
  });
});

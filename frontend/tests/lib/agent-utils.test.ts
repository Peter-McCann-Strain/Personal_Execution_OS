import { describe, it, expect } from "vitest";
import { AGENT_COLORS, AGENT_CHART_COLORS } from "@/lib/agent-utils";
import type { AgentName } from "@/types";

const ALL_AGENTS: AgentName[] = [
  "diary",
  "memory",
  "research",
  "review",
  "project",
  "communications",
  "tools",
  "notification",
  "save",
  "plan_day",
  "socratic",
];

describe("AGENT_COLORS", () => {
  it("has entries for all supported agents", () => {
    expect(Object.keys(AGENT_COLORS)).toHaveLength(ALL_AGENTS.length);
    for (const agent of ALL_AGENTS) {
      expect(AGENT_COLORS[agent]).toBeDefined();
    }
  });

  it("all values are CSS custom properties", () => {
    for (const color of Object.values(AGENT_COLORS)) {
      expect(color).toMatch(/^var\(--color-agent-/);
    }
  });
});

describe("AGENT_CHART_COLORS", () => {
  it("has entries for all supported agents", () => {
    expect(Object.keys(AGENT_CHART_COLORS)).toHaveLength(ALL_AGENTS.length);
    for (const agent of ALL_AGENTS) {
      expect(AGENT_CHART_COLORS[agent]).toBeDefined();
    }
  });

  it("all values are OKLCH color strings", () => {
    for (const color of Object.values(AGENT_CHART_COLORS)) {
      expect(color).toMatch(/^oklch\(/);
    }
  });

  it("has the same keys as AGENT_COLORS", () => {
    expect(Object.keys(AGENT_CHART_COLORS).sort()).toEqual(Object.keys(AGENT_COLORS).sort());
  });
});

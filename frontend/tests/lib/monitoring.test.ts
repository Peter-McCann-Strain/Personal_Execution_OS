import { describe, expect, it } from "vitest";
import {
  AGENT_OPTIONS,
  CHART_TOOLTIP_STYLE,
  MODEL_COLORS,
  MODEL_OPTIONS,
  PERIOD_OPTIONS,
  SORT_OPTIONS,
} from "@/lib/monitoring";

describe("monitoring constants", () => {
  it("exposes the supported time periods", () => {
    expect(PERIOD_OPTIONS).toEqual([
      { value: "today", label: "Today" },
      { value: "7d", label: "7 Days" },
      { value: "30d", label: "30 Days" },
    ]);
  });

  it("defines stable model colors and tooltip styling", () => {
    expect(MODEL_COLORS).toEqual({
      haiku: "oklch(0.6 0.15 155)",
      sonnet: "oklch(0.58 0.17 250)",
      opus: "oklch(0.58 0.2 290)",
    });
    expect(CHART_TOOLTIP_STYLE).toMatchObject({
      background: "var(--color-bg-elevated)",
      border: "1px solid var(--color-border-default)",
      color: "var(--color-fg-primary)",
      fontSize: 12,
    });
  });

  it("covers the expected filter and sorting options", () => {
    expect(AGENT_OPTIONS.map((option) => option.value)).toEqual([
      "all",
      "diary",
      "memory",
      "research",
      "review",
      "notification",
      "tools",
      "project",
      "communications",
      "save",
      "plan_day",
      "socratic",
    ]);
    expect(MODEL_OPTIONS.map((option) => option.value)).toEqual(["all", "haiku", "sonnet", "opus"]);
    expect(SORT_OPTIONS.map((option) => option.value)).toEqual([
      "newest",
      "oldest",
      "costliest",
      "cheapest",
      "slowest",
      "fastest",
    ]);
  });
});

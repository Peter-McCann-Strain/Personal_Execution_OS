/**
 * Shared constants and types for monitoring components.
 */

import type { AgentActionQueryParams } from "@/api/monitoring";
import type { AgentName } from "@/types";

// ─── Period ─────────────────────────────────────────────────

export type Period = "today" | "7d" | "30d";

export const PERIOD_OPTIONS: { value: Period; label: string }[] = [
  { value: "today", label: "Today" },
  { value: "7d", label: "7 Days" },
  { value: "30d", label: "30 Days" },
];

// ─── Model Colors (resolved OKLCH for Recharts) ────────────

export const MODEL_COLORS: Record<string, string> = {
  haiku: "oklch(0.6 0.15 155)",
  sonnet: "oklch(0.58 0.17 250)",
  opus: "oklch(0.58 0.2 290)",
};

// ─── Chart Tooltip Style ────────────────────────────────────

export const CHART_TOOLTIP_STYLE: React.CSSProperties = {
  background: "var(--color-bg-elevated)",
  border: "1px solid var(--color-border-default)",
  borderRadius: "var(--radius-md)",
  color: "var(--color-fg-primary)",
  fontSize: 12,
};

// ─── Agent Filter Options ───────────────────────────────────

export const AGENT_OPTIONS: { value: AgentName | "all"; label: string }[] = [
  { value: "all", label: "All Agents" },
  { value: "diary", label: "Diary" },
  { value: "memory", label: "Memory" },
  { value: "research", label: "Research" },
  { value: "review", label: "Review" },
  { value: "notification", label: "Notification" },
  { value: "tools", label: "Tools" },
  { value: "project", label: "Project" },
  { value: "communications", label: "Communications" },
  { value: "save", label: "Save" },
  { value: "plan_day", label: "Plan Day" },
  { value: "socratic", label: "Socratic" },
];

// ─── Model Filter Options ───────────────────────────────────

export const MODEL_OPTIONS: { value: string; label: string }[] = [
  { value: "all", label: "All Models" },
  { value: "haiku", label: "Haiku" },
  { value: "sonnet", label: "Sonnet" },
  { value: "opus", label: "Opus" },
];

// ─── Sort Options ───────────────────────────────────────────

export const SORT_OPTIONS: {
  value: AgentActionQueryParams["sort"];
  label: string;
}[] = [
  { value: "newest", label: "Newest" },
  { value: "oldest", label: "Oldest" },
  { value: "costliest", label: "Costliest" },
  { value: "cheapest", label: "Cheapest" },
  { value: "slowest", label: "Slowest" },
  { value: "fastest", label: "Fastest" },
];

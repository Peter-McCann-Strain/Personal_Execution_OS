import type { AgentName } from "@/types";

/**
 * Canonical agent color map using CSS custom properties.
 * Used by AgentBadge and other components that need agent-specific styling.
 */
export const AGENT_COLORS: Record<AgentName, string> = {
  diary: "var(--color-agent-diary)",
  memory: "var(--color-agent-memory)",
  research: "var(--color-agent-research)",
  review: "var(--color-agent-review)",
  project: "var(--color-agent-project)",
  communications: "var(--color-agent-comms)",
  tools: "var(--color-agent-tools)",
  notification: "var(--color-agent-notif)",
  save: "var(--color-agent-memory)",
  plan_day: "var(--color-agent-project)",
  socratic: "var(--color-agent-socratic)",
};

/**
 * Resolved OKLCH values for agent colors, used in contexts where CSS variables
 * cannot be used (e.g., Recharts chart fills).
 */
export const AGENT_CHART_COLORS: Record<AgentName, string> = {
  diary: "oklch(0.7 0.16 55)",
  memory: "oklch(0.62 0.13 220)",
  research: "oklch(0.58 0.2 290)",
  review: "oklch(0.75 0.15 80)",
  project: "oklch(0.58 0.18 250)",
  communications: "oklch(0.6 0.13 165)",
  tools: "oklch(0.68 0.17 55)",
  notification: "oklch(0.58 0.2 25)",
  save: "oklch(0.62 0.13 220)",
  plan_day: "oklch(0.58 0.18 250)",
  socratic: "oklch(0.66 0.12 200)",
};

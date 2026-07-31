import type { BloomLevel } from "@/api/tutorials";

const BLOOM_LEVELS: {
  level: BloomLevel;
  label: string;
  color: string;
  bgColor: string;
  borderColor: string;
}[] = [
  {
    level: "remember",
    label: "Remember",
    color: "var(--color-error-500)",
    bgColor: "var(--color-error-50)",
    borderColor: "var(--color-error-500)",
  },
  {
    level: "understand",
    label: "Understand",
    color: "var(--color-warning-500)",
    bgColor: "var(--color-warning-50)",
    borderColor: "var(--color-warning-500)",
  },
  {
    level: "apply",
    label: "Apply",
    color: "#eab308",
    bgColor: "#fefce8",
    borderColor: "#eab308",
  },
  {
    level: "analyze",
    label: "Analyze",
    color: "var(--color-success-500)",
    bgColor: "var(--color-success-50)",
    borderColor: "var(--color-success-500)",
  },
  {
    level: "evaluate",
    label: "Evaluate",
    color: "var(--color-info-500)",
    bgColor: "var(--color-info-50)",
    borderColor: "var(--color-info-500)",
  },
  {
    level: "create",
    label: "Create",
    color: "#a855f7",
    bgColor: "#faf5ff",
    borderColor: "#a855f7",
  },
];

function bloomLevelIndex(level: BloomLevel): number {
  return BLOOM_LEVELS.findIndex((b) => b.level === level);
}

function bloomColor(level: BloomLevel): string {
  return BLOOM_LEVELS[bloomLevelIndex(level)]?.color ?? "var(--color-fg-tertiary)";
}

export { BLOOM_LEVELS, bloomLevelIndex, bloomColor };

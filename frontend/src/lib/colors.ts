/**
 * Shared OKLCH color palettes used for deterministic avatar/event coloring.
 * Consolidates duplicate palettes from contact-card, email-list, and event-card.
 */

export const AVATAR_PALETTE = [
  "oklch(0.55 0.15 250)", // blue
  "oklch(0.58 0.18 290)", // purple
  "oklch(0.60 0.13 165)", // green
  "oklch(0.65 0.18 55)", // orange
  "oklch(0.55 0.19 25)", // red
  "oklch(0.58 0.17 200)", // cyan
  "oklch(0.62 0.15 120)", // lime
  "oklch(0.60 0.16 330)", // pink
  "oklch(0.55 0.14 80)", // yellow-green
  "oklch(0.58 0.16 140)", // teal
  "oklch(0.60 0.18 270)", // indigo
  "oklch(0.55 0.15 10)", // warm red
];

/**
 * Deterministic hash for mapping strings to array indices.
 * Used across avatar colors, event colors, etc.
 */
export function hashString(str: string): number {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash + str.charCodeAt(i)) | 0;
  }
  return Math.abs(hash);
}

/**
 * Pick a deterministic color from the palette for a given string.
 */
export function pickColor(key: string, palette = AVATAR_PALETTE): string {
  return palette[hashString(key) % palette.length];
}

/**
 * Create a light tinted background from an OKLCH color.
 * Used for event cards, timeline dots, etc.
 */
export function tintedBg(color: string, opacity = 20): string {
  return `color-mix(in oklch, ${color} ${opacity}%, transparent)`;
}

/**
 * Priority-to-CSS-class mapping for consistent priority coloring.
 */
export function getPriorityColorClass(priority: number): string {
  if (priority <= 2) return "bg-[var(--color-error-500)]";
  if (priority <= 4) return "bg-[var(--color-warning-500)]";
  if (priority <= 6) return "bg-[var(--color-warning-900)]";
  if (priority <= 8) return "bg-[var(--color-info-500)]";
  return "bg-[var(--color-fg-disabled)]";
}

/**
 * Progress percentage to color variant mapping.
 */
export function getProgressVariant(percent: number): "error" | "warning" | "default" | "success" {
  if (percent >= 75) return "success";
  if (percent >= 50) return "default";
  if (percent >= 25) return "warning";
  return "error";
}

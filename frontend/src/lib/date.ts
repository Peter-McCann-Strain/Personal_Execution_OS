/**
 * Centralized date/time formatting utilities.
 * Consolidates duplicate formatters from event-card, create-event-modal,
 * recent-activity, goal-tree, and contact-detail.
 */

import { format, isToday, parseISO } from "date-fns";

/**
 * Format an ISO datetime string as HH:MM (24h, en-GB locale).
 * Used for calendar events, time displays.
 */
export function formatTime(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

/**
 * Format an ISO datetime string for free slot display.
 * Example: "Mon, 10 Mar, 09:00"
 */
export function formatSlotTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("en-GB", {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * Format an ISO datetime string for activity log display.
 * Shows HH:MM for today, "d MMM HH:MM" otherwise.
 */
export function formatActionTime(dateStr: string): string {
  const d = parseISO(dateStr);
  if (isToday(d)) return format(d, "HH:mm");
  return format(d, "d MMM HH:mm");
}

/**
 * Format an ISO date string as a deadline display.
 * Returns "No deadline" for null values.
 */
export function formatDeadline(deadline: string | null): string {
  if (!deadline) return "No deadline";
  const d = new Date(deadline);
  return d.toLocaleDateString("en-GB", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

/**
 * Format an ISO date string as interaction date/time.
 * Returns both date ("10 Mar 2026") and time ("14:30").
 */
export function formatInteractionDateTime(iso: string): {
  date: string;
  time: string;
} {
  const d = new Date(iso);
  return {
    date: d.toLocaleDateString("en-GB", {
      year: "numeric",
      month: "short",
      day: "numeric",
    }),
    time: d.toLocaleTimeString("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
    }),
  };
}

/**
 * Format milliseconds as human-readable latency.
 */
export function formatLatency(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms)}ms`;
}

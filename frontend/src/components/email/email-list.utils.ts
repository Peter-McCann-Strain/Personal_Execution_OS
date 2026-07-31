import type { Email, TriageCategory } from "@/types";

interface TriageConfig {
  label: string;
  bgClass: string;
  textClass: string;
  pulse?: boolean;
}

const triageMap: Record<TriageCategory, TriageConfig> = {
  ACTION_REQUIRED: {
    label: "Action Required",
    bgClass: "bg-[var(--color-error-500)]",
    textClass: "text-white",
  },
  URGENT: {
    label: "Urgent",
    bgClass: "bg-[oklch(0.65_0.18_55)]",
    textClass: "text-white",
    pulse: true,
  },
  FYI: {
    label: "FYI",
    bgClass: "bg-[var(--color-info-500)]",
    textClass: "text-white",
  },
  DELEGATE: {
    label: "Delegate",
    bgClass: "bg-[oklch(0.58_0.18_290)]",
    textClass: "text-white",
  },
  ARCHIVE: {
    label: "Archive",
    bgClass: "bg-[var(--color-fg-disabled)]",
    textClass: "text-white",
  },
};

function getSender(email: Email): string {
  const h = email.headers ?? {};
  const from = h["From"] || h["from"] || "";
  const match = from.match(/^([^<]+)/);
  return match ? match[1].trim() : from;
}

function getSubject(email: Email): string {
  const h = email.headers ?? {};
  return h["Subject"] || h["subject"] || "(no subject)";
}

function isUnread(email: Email): boolean {
  return (email.labelIds ?? []).includes("UNREAD");
}

export { triageMap, getSender, getSubject, isUnread };
export type { TriageConfig };

import { api, apiPath } from "./client";
import { API_PATHS } from "./generated/paths";
import type { AgentAction, CalendarEvent, Episode, Goal, Notification } from "@/types";

// ─── Dashboard Stats ────────────────────────────────────────
export type ConnectorErrorCategory = "token_expired" | "rate_limited" | "backend_error" | "unknown";

export interface StatCardData {
  value: number | null;
  label: string;
  trend: number | null;
  sparkline: number[];
  subLabel: string | null;
  status: "available" | "unavailable" | "not_configured";
  message: string | null;
  errorCategory: ConnectorErrorCategory | null;
  actionable: boolean;
  actionUrl: string | null;
}

export interface DashboardStats {
  mood: StatCardData;
  projects: StatCardData;
  emails: StatCardData;
  events: StatCardData;
}

export function getDashboardStats(): Promise<DashboardStats> {
  return api.get<DashboardStats>(apiPath(API_PATHS.apiDashboardStats));
}

// ─── Morning Briefing ───────────────────────────────────────
export interface BriefingGreeting {
  greeting: string;
  dateString: string;
  cognitiveLoad: number | string;
  summary: string;
}

export interface BriefingContent {
  title: string;
  source: string;
  url: string;
  relevance: number;
}

export interface MorningBriefing {
  greeting: BriefingGreeting;
  schedule: CalendarEvent[];
  notifications: Notification[];
  content: BriefingContent[];
  status: "ready" | "partial" | "not_configured";
  notices: Array<{
    source: "calendar" | "notifications" | "content";
    status: "available" | "unavailable" | "not_configured";
    message: string;
    errorCategory?: ConnectorErrorCategory | null;
    actionable?: boolean;
    actionUrl?: string | null;
  }>;
}

export function getMorningBriefing(): Promise<MorningBriefing> {
  return api.get<MorningBriefing>(apiPath(API_PATHS.apiDashboardBriefing));
}

// ─── Mood/Energy Trends ─────────────────────────────────────
export interface MoodEnergyPoint {
  date: string;
  mood: number | null;
  energy: number | null;
}

export function getMoodEnergyTrends(days: number = 30): Promise<MoodEnergyPoint[]> {
  return api.get<MoodEnergyPoint[]>(apiPath(API_PATHS.apiDashboardTrendsMoodEnergy), {
    days,
  });
}

// ─── Recent Diary ───────────────────────────────────────────
export function getRecentDiaryEntries(limit: number = 3): Promise<Episode[]> {
  return api.get<Episode[]>(apiPath(API_PATHS.apiDashboardDiaryRecent), { limit });
}

// ─── Goal Progress ──────────────────────────────────────────
export function getActiveGoals(limit: number = 5): Promise<Goal[]> {
  return api.get<Goal[]>(apiPath(API_PATHS.apiDashboardGoals), {
    status: "active",
    limit,
  });
}

// ─── Agent Activity ─────────────────────────────────────────
export function getRecentAgentActivity(limit: number = 5): Promise<AgentAction[]> {
  return api.get<AgentAction[]>(apiPath(API_PATHS.apiDashboardActivityRecent), {
    limit,
  });
}

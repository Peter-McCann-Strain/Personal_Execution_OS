import { api, apiPath } from "./client";
import { API_PATHS } from "./generated/paths";

// ─── Types ─────────────────────────────────────────────────

export type HabitFrequency = "daily" | "weekly" | "monthly" | "custom";

export interface Habit {
  id: string;
  name: string;
  description: string | null;
  frequency: HabitFrequency;
  frequency_days: number | null;
  current_streak: number;
  longest_streak: number;
  total_completions: number;
  last_completed_at: string | null;
  active: boolean;
  tags: string[];
  created_at: string;
}

export interface HabitLog {
  id: string;
  habit_id: string;
  completed_at: string;
  note: string | null;
  source: string;
}

export interface CreateHabitData {
  name: string;
  description?: string;
  frequency?: HabitFrequency;
  frequency_days?: number;
  tags?: string[];
}

// ─── API Functions ─────────────────────────────────────────

export function getHabits(): Promise<Habit[]> {
  return api.get<Habit[]>(apiPath(API_PATHS.apiHabits));
}

export function createHabit(data: CreateHabitData): Promise<Habit> {
  return api.post<Habit>(apiPath(API_PATHS.apiHabits), data);
}

export function getHabit(id: string): Promise<Habit> {
  return api.get<Habit>(apiPath(API_PATHS.apiHabitsByHabitId, { habit_id: id }));
}

export function completeHabit(id: string, note?: string): Promise<HabitLog> {
  const path = apiPath(API_PATHS.apiHabitsByHabitIdComplete, { habit_id: id });

  if (note == null) {
    return api.post<HabitLog>(path);
  }

  return api.post<HabitLog>(path, { note });
}

export function getHabitLogs(id: string, days?: number): Promise<HabitLog[]> {
  const path = apiPath(API_PATHS.apiHabitsByHabitIdLogs, { habit_id: id });

  if (days == null) {
    return api.get<HabitLog[]>(path);
  }

  return api.get<HabitLog[]>(path, { days });
}

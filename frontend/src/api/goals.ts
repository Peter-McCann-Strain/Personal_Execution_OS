import { api, apiPath, getWithQuery } from "./client";
import { API_PATHS } from "./generated/paths";
import type { Goal, GoalStatus, PaginatedResponse } from "@/types";

// ─── Query Parameters ───────────────────────────────────────
export interface GoalQueryParams {
  limit?: number;
  offset?: number;
  status?: GoalStatus;
  goal_type?: string;
  sort?: "priority" | "progress" | "deadline" | "created_at";
  order?: "asc" | "desc";
}

// ─── Fetch Goals ────────────────────────────────────────────
export function getGoals(params: GoalQueryParams = {}): Promise<PaginatedResponse<Goal>> {
  return getWithQuery<PaginatedResponse<Goal>, GoalQueryParams>(
    apiPath(API_PATHS.apiGoals),
    params,
  );
}

// ─── Fetch Single Goal ──────────────────────────────────────
export function getGoal(id: string): Promise<Goal> {
  return api.get<Goal>(apiPath(API_PATHS.apiGoalsByGoalId, { goal_id: id }));
}

// ─── Update Goal Progress ───────────────────────────────────
export function updateGoalProgress(id: string, progress: number): Promise<Goal> {
  return api.patch<Goal>(apiPath(API_PATHS.apiGoalsByGoalId, { goal_id: id }), {
    progress,
  });
}

// ─── Create Goal ────────────────────────────────────────────
export interface CreateGoalData {
  title: string;
  goal_type?: string;
  parent_id?: string;
  priority?: number;
  deadline?: string;
}

export function createGoal(data: CreateGoalData): Promise<Goal> {
  return api.post<Goal>(apiPath(API_PATHS.apiGoals), data);
}

// ─── Fetch Child Goals ──────────────────────────────────────
export function getChildGoals(goalId: string): Promise<Goal[]> {
  return api.get<Goal[]>(apiPath(API_PATHS.apiGoalsByGoalIdChildren, { goal_id: goalId }));
}

// ─── Delete Goal ────────────────────────────────────────────
export function deleteGoal(goalId: string): Promise<void> {
  return api.delete(apiPath(API_PATHS.apiGoalsByGoalId, { goal_id: goalId }));
}

import { api, apiPath, getWithQuery } from "./client";
import { API_PATHS } from "./generated/paths";
import type { PaginatedResponse } from "@/types";

// ─── Decision Types ────────────────────────────────────────

export type DecisionStatus = "pending_review" | "reviewed" | "archived";

export interface Decision {
  id: string;
  title: string;
  context: string | null;
  options_considered: string[];
  decision_made: string;
  reasoning: string | null;
  expected_outcome: string | null;
  actual_outcome: string | null;
  outcome_rating: number | null;
  tags: string[];
  review_date: string | null;
  status: DecisionStatus;
  created_at: string;
  updated_at: string;
}

export interface CreateDecisionData {
  title: string;
  decision_made: string;
  context?: string;
  options_considered?: string[];
  reasoning?: string;
  expected_outcome?: string;
  tags?: string[];
  review_date?: string;
}

export interface RecordOutcomeData {
  actual_outcome: string;
  outcome_rating?: number;
}

// ─── Query Parameters ──────────────────────────────────────

export interface DecisionQueryParams {
  status?: DecisionStatus;
  limit?: number;
  offset?: number;
}

// ─── Fetch Decisions ───────────────────────────────────────

export function getDecisions(
  params: DecisionQueryParams = {},
): Promise<PaginatedResponse<Decision>> {
  return getWithQuery<PaginatedResponse<Decision>, DecisionQueryParams>(
    apiPath(API_PATHS.apiDecisions),
    params,
  );
}

// ─── Fetch Decisions Due for Review ────────────────────────

export function getDecisionsDueReview(): Promise<Decision[]> {
  return api.get<Decision[]>(apiPath(API_PATHS.apiDecisionsDueReview));
}

// ─── Fetch Single Decision ─────────────────────────────────

export function getDecision(id: string): Promise<Decision> {
  return api.get<Decision>(apiPath(API_PATHS.apiDecisionsByDecisionId, { decision_id: id }));
}

// ─── Create Decision ───────────────────────────────────────

export function createDecision(data: CreateDecisionData): Promise<Decision> {
  return api.post<Decision>(apiPath(API_PATHS.apiDecisions), data);
}

// ─── Record Outcome ────────────────────────────────────────

export function recordOutcome(id: string, data: RecordOutcomeData): Promise<Decision> {
  return api.patch<Decision>(
    apiPath(API_PATHS.apiDecisionsByDecisionIdOutcome, { decision_id: id }),
    data,
  );
}

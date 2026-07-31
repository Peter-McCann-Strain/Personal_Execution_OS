import { api, apiPath, getWithQuery } from "./client";
import { API_PATHS } from "./generated/paths";
import type { PaginatedResponse } from "@/types";

// ─── Bloom Taxonomy ─────────────────────────────────────────
export type BloomLevel = "remember" | "understand" | "apply" | "analyze" | "evaluate" | "create";

export type TutorialPhase = "submitted" | "dialogue" | "complete";

// ─── Tutorial Summary (list view) ──────────────────────────
export interface Tutorial {
  id: string;
  topic: string;
  work_type: string;
  phase: TutorialPhase;
  turn_count: number;
  bloom_start: BloomLevel | null;
  bloom_end: BloomLevel | null;
  speaking_ratio_student_pct: number | null;
  knowledge_gaps_found: number;
  knowledge_gaps_addressed: number;
  created_at: string;
  completed_at: string | null;
}

// ─── Transcript Turn ────────────────────────────────────────
export interface TranscriptTurn {
  speaker: "tutor" | "student";
  content: string;
  turn?: number;
  bloom_level?: BloomLevel;
  phase?: TutorialPhase;
}

// ─── Tutorial Detail (full view) ────────────────────────────
export interface TutorialDetail extends Tutorial {
  submitted_work: string | null;
  propositions: string[] | null;
  transcript: TranscriptTurn[];
  analysis: TutorialAnalysis | null;
}

export interface TutorialAnalysis {
  bloom_progression: BloomLevel[];
  knowledge_gaps_found: number;
  knowledge_gaps_addressed: number;
  speaking_ratio_student_pct: number;
  summary?: string;
  strengths?: string[];
  areas_for_improvement?: string[];
  [key: string]: unknown;
}

// ─── Turn Response ──────────────────────────────────────────
export interface TutorialTurnResponse {
  tutorial_id: string;
  content: string;
  phase: TutorialPhase;
  speaker: "tutor" | "student";
  turn?: number;
  bloom_level?: BloomLevel;
  analysis?: TutorialAnalysis;
}

// ─── Query Parameters ───────────────────────────────────────
export interface TutorialQueryParams {
  limit?: number;
  offset?: number;
}

// ─── API Functions ──────────────────────────────────────────

export function getTutorials(
  params: TutorialQueryParams = {},
): Promise<PaginatedResponse<Tutorial>> {
  return getWithQuery<PaginatedResponse<Tutorial>, TutorialQueryParams>(
    apiPath(API_PATHS.apiTutorials),
    params,
  );
}

export function getTutorial(id: string): Promise<TutorialDetail> {
  return api.get<TutorialDetail>(apiPath(API_PATHS.apiTutorialsByTutorialId, { tutorial_id: id }));
}

export function startTutorial(id: string): Promise<TutorialTurnResponse> {
  return api.post<TutorialTurnResponse>(
    apiPath(API_PATHS.apiTutorialsByTutorialIdStart, { tutorial_id: id }),
  );
}

export function sendTutorialTurn(id: string, message: string): Promise<TutorialTurnResponse> {
  return api.post<TutorialTurnResponse>(
    apiPath(API_PATHS.apiTutorialsByTutorialIdTurn, { tutorial_id: id }),
    { message },
  );
}

export function endTutorial(id: string): Promise<TutorialTurnResponse> {
  return api.post<TutorialTurnResponse>(
    apiPath(API_PATHS.apiTutorialsByTutorialIdEnd, { tutorial_id: id }),
  );
}

import { api, apiPath, getWithQuery } from "./client";
import { API_PATHS } from "./generated/paths";
import type { WeeklyReview, PaginatedResponse } from "@/types";

// ─── Query Parameters ───────────────────────────────────────
export interface ReviewQueryParams {
  limit?: number;
  offset?: number;
  review_type?: "weekly" | "quarterly";
  sort?: "created_at" | "period";
  order?: "asc" | "desc";
}

// ─── Fetch Reviews ──────────────────────────────────────────
export function getReviews(
  params: ReviewQueryParams = {},
): Promise<PaginatedResponse<WeeklyReview>> {
  return getWithQuery<PaginatedResponse<WeeklyReview>, ReviewQueryParams>(
    apiPath(API_PATHS.apiReviews),
    params,
  );
}

// ─── Fetch Single Review ────────────────────────────────────
export function getReview(id: string): Promise<WeeklyReview> {
  return api.get<WeeklyReview>(apiPath(API_PATHS.apiReviewsByReviewId, { review_id: id }));
}

// ─── Generate Review ────────────────────────────────────────
export function generateReview(type: "weekly" | "quarterly"): Promise<WeeklyReview> {
  return api.post<WeeklyReview>(apiPath(API_PATHS.apiReviewsGenerate), { type });
}

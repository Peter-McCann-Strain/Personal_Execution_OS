import { api, apiPath, getWithQuery } from "./client";
import { API_PATHS } from "./generated/paths";
import type { Episode, PaginatedResponse, ParaCategory, EpisodeType } from "@/types";

// ─── Query Parameters ───────────────────────────────────────
export interface EpisodeQueryParams {
  limit?: number;
  offset?: number;
  sort?: "created_at" | "mood_score" | "energy_rating";
  order?: "asc" | "desc";
  date_from?: string;
  date_to?: string;
  para_category?: ParaCategory;
  episode_type?: EpisodeType;
  tags?: string[];
  people?: string[];
  mood_min?: number;
  mood_max?: number;
}

// ─── Fetch Episodes ─────────────────────────────────────────
export function getEpisodes(params: EpisodeQueryParams = {}): Promise<PaginatedResponse<Episode>> {
  return getWithQuery<PaginatedResponse<Episode>, EpisodeQueryParams>(
    apiPath(API_PATHS.apiEpisodes),
    params,
  );
}

// ─── Fetch Single Episode ───────────────────────────────────
export function getEpisode(id: string): Promise<Episode> {
  return api.get<Episode>(apiPath(API_PATHS.apiEpisodesByEpisodeId, { episode_id: id }));
}

// ─── Episode Stats / Aggregations ───────────────────────────
export interface EpisodeStats {
  totalEntries: number;
  averageMood: number | null;
  averageEnergy: number | null;
  moodTrend: MoodTrendPoint[];
  tagFrequency: TagCount[];
  paraDistribution: ParaCount[];
}

export interface MoodTrendPoint {
  date: string;
  mood: number | null;
  energy: number | null;
  count: number;
}

export interface TagCount {
  tag: string;
  count: number;
}

export interface ParaCount {
  category: ParaCategory | "unclassified";
  count: number;
}

export function getEpisodeStats(days: number = 30): Promise<EpisodeStats> {
  return api.get<EpisodeStats>(apiPath(API_PATHS.apiEpisodesStats), { days });
}

// ─── Fetch Episodes by Date Range ──────────────────────────
export function getEpisodesByDateRange(start: string, end: string): Promise<Episode[]> {
  return api.get<Episode[]>(apiPath(API_PATHS.apiEpisodesDateRange), {
    start,
    end,
  });
}

// ─── Update Episode ────────────────────────────────────────
export function updateEpisode(id: string, data: Partial<Episode>): Promise<Episode> {
  return api.patch<Episode>(apiPath(API_PATHS.apiEpisodesByEpisodeId, { episode_id: id }), data);
}

// ─── Delete Episode ────────────────────────────────────────
export function deleteEpisode(id: string): Promise<void> {
  return api.delete(apiPath(API_PATHS.apiEpisodesByEpisodeId, { episode_id: id }));
}

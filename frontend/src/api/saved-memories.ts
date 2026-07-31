import { api, apiPath, getWithQuery } from "./client";
import { API_PATHS } from "./generated/paths";
import type { PaginatedResponse, SavedMemory } from "@/types";

export interface SavedMemoryQueryParams {
  limit?: number;
  offset?: number;
  search?: string;
  scope?: SavedMemory["scope"];
  state?: SavedMemory["state"];
}

export interface CreateSavedMemoryData {
  title: string;
  content: string;
  scope?: SavedMemory["scope"];
  scope_key?: string;
  source_type?: string;
  source_id?: string;
  provenance?: Record<string, unknown>;
  pinned?: boolean;
  auto_captured?: boolean;
}

export interface UpdateSavedMemoryData extends Partial<CreateSavedMemoryData> {
  state?: SavedMemory["state"];
  confirm_now?: boolean;
  mark_used?: boolean;
}

export interface MergeSavedMemoriesData {
  target_memory_id: string;
  source_memory_ids: string[];
}

export function listSavedMemories(
  params: SavedMemoryQueryParams = {},
): Promise<PaginatedResponse<SavedMemory>> {
  return getWithQuery<PaginatedResponse<SavedMemory>, SavedMemoryQueryParams>(
    apiPath(API_PATHS.apiSavedMemories),
    params,
  );
}

export function createSavedMemory(data: CreateSavedMemoryData): Promise<SavedMemory> {
  return api.post<SavedMemory>(apiPath(API_PATHS.apiSavedMemories), data);
}

export function mergeSavedMemories(data: MergeSavedMemoriesData): Promise<SavedMemory> {
  return api.post<SavedMemory>(apiPath(API_PATHS.apiSavedMemoriesMerge), data);
}

export function updateSavedMemory(
  memoryId: string,
  data: UpdateSavedMemoryData,
): Promise<SavedMemory> {
  return api.patch<SavedMemory>(
    apiPath(API_PATHS.apiSavedMemoriesByMemoryId, { memory_id: memoryId }),
    data,
  );
}

export function deleteSavedMemory(memoryId: string): Promise<void> {
  return api.delete(apiPath(API_PATHS.apiSavedMemoriesByMemoryId, { memory_id: memoryId }));
}

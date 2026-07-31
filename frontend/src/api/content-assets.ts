import { api, apiPath, getWithQuery } from "./client";
import { API_PATHS } from "./generated/paths";
import type { ContentAsset, PaginatedResponse } from "@/types";

export interface ContentAssetQueryParams {
  asset_type?: string;
  status?: string;
  note_id?: string;
  limit?: number;
  offset?: number;
}

export interface CreateContentAssetData {
  title?: string;
  note_id?: string;
  project_id?: string;
  task_id?: string;
  asset_type?: string;
  status?: string;
  source_pack?: Record<string, unknown>;
  template_prompt?: string;
  run_notes?: string;
  metadata?: Record<string, unknown>;
}

export interface UpdateContentAssetData {
  title?: string;
  status?: string;
  source_pack?: Record<string, unknown>;
  template_prompt?: string;
  run_notes?: string;
  metadata?: Record<string, unknown>;
}

export function getContentAssets(
  params: ContentAssetQueryParams = {},
): Promise<PaginatedResponse<ContentAsset>> {
  return getWithQuery<PaginatedResponse<ContentAsset>, ContentAssetQueryParams>(
    apiPath(API_PATHS.apiContentAssets),
    params,
  );
}

export function createContentAsset(data: CreateContentAssetData): Promise<ContentAsset> {
  return api.post<ContentAsset>(apiPath(API_PATHS.apiContentAssets), data);
}

export function generateContentAssetSourcePack(id: string): Promise<ContentAsset> {
  return api.post<ContentAsset>(
    apiPath(API_PATHS.apiContentAssetsByAssetIdSourcePack, { asset_id: id }),
  );
}

export function updateContentAsset(
  id: string,
  data: UpdateContentAssetData,
): Promise<ContentAsset> {
  return api.patch<ContentAsset>(
    apiPath(API_PATHS.apiContentAssetsByAssetId, { asset_id: id }),
    data,
  );
}

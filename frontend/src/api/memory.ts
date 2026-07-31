import { api, apiPath, getWithQuery } from "./client";
import { API_PATHS } from "./generated/paths";
import type { MemoryAnswer, Entity, EntityRelationship, RelatedEntity } from "@/types";

export interface SearchMemoryRequest {
  query: string;
  sensitive_mode?: boolean;
  suppressed_sources?: string[];
}

export async function searchMemory(input: string | SearchMemoryRequest): Promise<MemoryAnswer> {
  const payload: SearchMemoryRequest = typeof input === "string" ? { query: input } : input;
  return api.post<MemoryAnswer>(apiPath(API_PATHS.apiSearch), payload);
}

export interface GetEntitiesParams {
  entity_type?: string;
  search?: string;
  limit?: number;
  offset?: number;
}

export async function getEntities(params?: GetEntitiesParams): Promise<Entity[]> {
  return getWithQuery<Entity[], GetEntitiesParams>(apiPath(API_PATHS.apiEntities), params);
}

export async function getEntityRelationships(): Promise<EntityRelationship[]> {
  return api.get<EntityRelationship[]>(apiPath(API_PATHS.apiEntitiesRelationships));
}

export async function getEntity(id: string): Promise<Entity> {
  return api.get<Entity>(apiPath(API_PATHS.apiEntitiesByEntityId, { entity_id: id }));
}

export async function getRelatedEntities(entityId: string): Promise<RelatedEntity[]> {
  return api.get<RelatedEntity[]>(
    apiPath(API_PATHS.apiEntitiesByEntityIdRelated, { entity_id: entityId }),
  );
}

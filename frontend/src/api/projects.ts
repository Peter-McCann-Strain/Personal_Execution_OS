import { api, apiPath, getWithQuery } from "./client";
import { API_PATHS } from "./generated/paths";
import type {
  PaginatedResponse,
  Project,
  ProjectDraft,
  ProjectStatus,
  Appetite,
  Task,
  TaskStatus,
} from "@/types";

export interface ProjectQueryParams {
  limit?: number;
  offset?: number;
  sort?: "deadline" | "progress" | "created_at" | "title";
  order?: "asc" | "desc";
  status?: ProjectStatus;
  appetite?: Appetite;
}

export interface ProjectDraftQueryParams {
  limit?: number;
  offset?: number;
  status?: string;
  user_id?: string;
}

export function getProjects(params: ProjectQueryParams = {}): Promise<PaginatedResponse<Project>> {
  return getWithQuery<PaginatedResponse<Project>, ProjectQueryParams>(
    apiPath(API_PATHS.apiProjects),
    params,
  );
}

export function getProject(id: string): Promise<Project> {
  return api.get<Project>(apiPath(API_PATHS.apiProjectsByProjectId, { project_id: id }));
}

export interface CreateProjectData {
  title: string;
  description?: string;
  appetite?: Appetite;
  deadline?: string;
}

export function createProject(data: CreateProjectData): Promise<Project> {
  return api.post<Project>(apiPath(API_PATHS.apiProjects), data);
}

export function getProjectDrafts(
  params: ProjectDraftQueryParams = {},
): Promise<PaginatedResponse<ProjectDraft>> {
  return getWithQuery<PaginatedResponse<ProjectDraft>, ProjectDraftQueryParams>(
    apiPath(API_PATHS.apiProjectDrafts),
    params,
  );
}

export function applyProjectDraft(draftId: string): Promise<Project> {
  return api.post<Project>(
    apiPath(API_PATHS.apiProjectDraftsByDraftIdApply, { draft_id: draftId }),
  );
}

export interface UpdateTaskData {
  title?: string;
  description?: string;
  status?: TaskStatus;
  estimate_hours?: number;
  actual_hours?: number;
  wsjf_score?: number;
  context_tags?: string[];
  blocked_reason?: string;
  dependency_task_ids?: string[];
}

export function updateTask(id: string, data: UpdateTaskData): Promise<Task> {
  return api.patch<Task>(apiPath(API_PATHS.apiTasksByTaskId, { task_id: id }), data);
}

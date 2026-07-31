import { api, apiPath, getWithQuery } from "./client";
import { API_PATHS } from "./generated/paths";
import type { PaginatedResponse, ScheduledAction, ScheduledActionRun } from "@/types";

export interface ScheduledActionQueryParams {
  limit?: number;
  offset?: number;
  status?: ScheduledAction["status"];
}

export interface CreateScheduledActionData {
  title: string;
  prompt: string;
  schedule_type: ScheduledAction["schedule_type"];
  schedule_config?: Record<string, unknown>;
  timezone?: string;
  delivery_channel?: ScheduledAction["delivery_channel"];
  status?: ScheduledAction["status"];
}

export type UpdateScheduledActionData = Partial<CreateScheduledActionData>;

export function listScheduledActions(
  params: ScheduledActionQueryParams = {},
): Promise<PaginatedResponse<ScheduledAction>> {
  return getWithQuery<PaginatedResponse<ScheduledAction>, ScheduledActionQueryParams>(
    apiPath(API_PATHS.apiScheduledActions),
    params,
  );
}

export function createScheduledAction(data: CreateScheduledActionData): Promise<ScheduledAction> {
  return api.post<ScheduledAction>(apiPath(API_PATHS.apiScheduledActions), data);
}

export function updateScheduledAction(
  actionId: string,
  data: UpdateScheduledActionData,
): Promise<ScheduledAction> {
  return api.patch<ScheduledAction>(
    apiPath(API_PATHS.apiScheduledActionsByActionId, { action_id: actionId }),
    data,
  );
}

export function deleteScheduledAction(actionId: string): Promise<void> {
  return api.delete(apiPath(API_PATHS.apiScheduledActionsByActionId, { action_id: actionId }));
}

export function runScheduledActionNow(actionId: string): Promise<ScheduledActionRun> {
  return api.post<ScheduledActionRun>(
    apiPath(API_PATHS.apiScheduledActionsByActionIdRun, { action_id: actionId }),
  );
}

export function listScheduledActionRuns(actionId?: string): Promise<ScheduledActionRun[]> {
  return getWithQuery<ScheduledActionRun[], { action_id?: string }>(
    apiPath(API_PATHS.apiScheduledActionsRuns),
    actionId ? { action_id: actionId } : {},
  );
}

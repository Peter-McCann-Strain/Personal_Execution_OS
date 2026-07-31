import { api, apiPath, getWithQuery } from "./client";
import { API_PATHS } from "./generated/paths";
import type { AgentRunDetail, AgentRunSummary, PaginatedResponse } from "@/types";

export interface AgentRunQueryParams {
  limit?: number;
  offset?: number;
  status?: string;
}

export interface ApprovalActionResponse {
  status: string;
  response_content: string;
  workflow_status: string;
}

export function getAgentRuns(
  params: AgentRunQueryParams = {},
): Promise<PaginatedResponse<AgentRunSummary>> {
  return getWithQuery<PaginatedResponse<AgentRunSummary>, AgentRunQueryParams>(
    apiPath(API_PATHS.apiAgentRuns),
    params,
  );
}

export function getAgentRun(workflowId: string): Promise<AgentRunDetail> {
  return api.get<AgentRunDetail>(
    apiPath(API_PATHS.apiAgentRunsByWorkflowId, { workflow_id: workflowId }),
  );
}

export function approveAgentRunRequest(
  workflowId: string,
  approvalId: string,
): Promise<ApprovalActionResponse> {
  return api.post<ApprovalActionResponse>(
    apiPath(API_PATHS.apiAgentRunsByWorkflowIdApprovalsByApprovalIdApprove, {
      workflow_id: workflowId,
      approval_id: approvalId,
    }),
  );
}

export function rejectAgentRunRequest(
  workflowId: string,
  approvalId: string,
): Promise<ApprovalActionResponse> {
  return api.post<ApprovalActionResponse>(
    apiPath(API_PATHS.apiAgentRunsByWorkflowIdApprovalsByApprovalIdReject, {
      workflow_id: workflowId,
      approval_id: approvalId,
    }),
  );
}

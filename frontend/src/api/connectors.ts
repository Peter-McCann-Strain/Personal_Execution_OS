import { api, apiPath, getWithQuery } from "./client";
import { API_PATHS } from "./generated/paths";
import type {
  ConnectorAccount,
  ConnectorDocument,
  ConnectorSyncJob,
  PaginatedResponse,
} from "@/types";

export interface UpdateConnectorAccountData {
  display_name?: string;
  auto_use?: boolean;
  background_access?: boolean;
  sync_enabled?: boolean;
}

export interface SyncConnectorData {
  sync_type?: string;
  max_items?: number;
}

export interface ConnectorDocumentQueryParams {
  limit?: number;
  offset?: number;
  account_id?: string;
  source_type?: string;
  search?: string;
}

export interface StartGoogleOAuthResponse {
  auth_url: string;
  state_expires_at: string;
}

export function listConnectorAccounts(): Promise<ConnectorAccount[]> {
  return api.get<ConnectorAccount[]>(apiPath(API_PATHS.apiConnectorsAccounts));
}

export function startGoogleOAuth(connectorType: string): Promise<StartGoogleOAuthResponse> {
  const path = `${apiPath(API_PATHS.apiConnectorsOauthGoogleStart)}?connector_type=${encodeURIComponent(connectorType)}`;
  return api.post<StartGoogleOAuthResponse>(path, undefined);
}

export function updateConnectorAccount(
  accountId: string,
  data: UpdateConnectorAccountData,
): Promise<ConnectorAccount> {
  return api.patch<ConnectorAccount>(
    apiPath(API_PATHS.apiConnectorsAccountsByAccountId, { account_id: accountId }),
    data,
  );
}

export function deleteConnectorAccount(accountId: string): Promise<void> {
  return api.delete<void>(
    apiPath(API_PATHS.apiConnectorsAccountsByAccountId, { account_id: accountId }),
  );
}

export function syncConnectorAccount(
  accountId: string,
  data: SyncConnectorData = {},
): Promise<ConnectorSyncJob> {
  return api.post<ConnectorSyncJob>(
    apiPath(API_PATHS.apiConnectorsAccountsByAccountIdSync, { account_id: accountId }),
    data,
  );
}

export function listConnectorSyncJobs(): Promise<ConnectorSyncJob[]> {
  return api.get<ConnectorSyncJob[]>(apiPath(API_PATHS.apiConnectorsSyncJobs));
}

export function listConnectorDocuments(
  params: ConnectorDocumentQueryParams = {},
): Promise<PaginatedResponse<ConnectorDocument>> {
  return getWithQuery<PaginatedResponse<ConnectorDocument>, ConnectorDocumentQueryParams>(
    apiPath(API_PATHS.apiConnectorsDocuments),
    params,
  );
}

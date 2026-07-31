import { api, apiPath } from "./client";
import { API_PATHS } from "./generated/paths";

export interface CoreDataExportRequest {
  id: string;
  status: string;
  storage_url: string | null;
  expires_at: string | null;
  created_at: string;
  completed_at: string | null;
}

export function listCoreDataExports(): Promise<CoreDataExportRequest[]> {
  return api.get<CoreDataExportRequest[]>(apiPath(API_PATHS.apiAccountCoreDataExports));
}

export function createCoreDataExport(): Promise<CoreDataExportRequest> {
  return api.post<CoreDataExportRequest>(apiPath(API_PATHS.apiAccountCoreDataExports));
}

export function downloadCoreDataExport(exportId: string): Promise<Record<string, unknown>> {
  return api.get<Record<string, unknown>>(
    apiPath(API_PATHS.apiAccountCoreDataExportsByExportIdDownload, { export_id: exportId }),
  );
}

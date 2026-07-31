import { api, apiPath, getWithQuery } from "./client";
import { API_PATHS } from "./generated/paths";
import type { Email, TriageCategory, OffsetPaginatedResponse } from "@/types";

export interface GetEmailsParams {
  search?: string;
  triage?: TriageCategory;
  unread_only?: boolean;
  limit?: number;
  offset?: number;
}

export async function getEmails(params?: GetEmailsParams): Promise<OffsetPaginatedResponse<Email>> {
  return getWithQuery<OffsetPaginatedResponse<Email>, GetEmailsParams>(
    apiPath(API_PATHS.apiEmailInbox),
    params,
  );
}

export async function getEmail(id: string): Promise<Email> {
  return api.get<Email>(apiPath(API_PATHS.apiEmailByMessageId, { message_id: id }));
}

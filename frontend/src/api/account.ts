import { api, apiPath } from "./client";
import { API_PATHS } from "./generated/paths";

export interface Principal {
  subject: string;
  user_id: string;
  account_id: string;
  role: string;
  plan: string;
  scopes: string[];
  auth_method: string;
}

export function getCurrentPrincipal(): Promise<Principal> {
  return api.get<Principal>(apiPath(API_PATHS.apiAccountMe));
}

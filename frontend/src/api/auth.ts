import { api, apiPath } from "./client";
import { API_PATHS } from "./generated/paths";

export interface SetupStatus {
  initialized: boolean;
  auth_mode: string;
}

export interface AuthSession {
  authenticated: boolean;
  subject: string;
  role: string;
  expires_at: string | null;
}

export function getSetupStatus(): Promise<SetupStatus> {
  return api.get<SetupStatus>(apiPath(API_PATHS.apiSetupStatus));
}

export function initializeOwner(password: string): Promise<AuthSession> {
  return api.post<AuthSession>(apiPath(API_PATHS.apiSetupInitialize), { password });
}

export function loginWithPassword(password: string): Promise<AuthSession> {
  return api.post<AuthSession>(apiPath(API_PATHS.apiAuthLogin), { password });
}

export function getCurrentSession(): Promise<AuthSession> {
  return api.get<AuthSession>(apiPath(API_PATHS.apiAuthSession));
}

export function logoutCurrentSession(): Promise<void> {
  return api.post<void>(apiPath(API_PATHS.apiAuthLogout));
}

export function changeOwnerPassword(currentPassword: string, newPassword: string): Promise<void> {
  return api.post<void>(apiPath(API_PATHS.apiAuthChangePassword), {
    current_password: currentPassword,
    new_password: newPassword,
  });
}

export function revokeAllOwnerSessions(currentPassword: string): Promise<void> {
  return api.post<void>(apiPath(API_PATHS.apiAuthSessionsRevokeAll), {
    current_password: currentPassword,
  });
}

const DEFAULT_APP_PATH = "/dashboard";
const LOGIN_PATH = "/login";
const SETUP_PATH = "/setup";

const rawAllowInsecureDevAuth = import.meta.env.VITE_ALLOW_INSECURE_DEV_AUTH as string | undefined;

export const isLegacyDevAuthEnabled =
  rawAllowInsecureDevAuth?.trim().toLowerCase() === "true" && !import.meta.env.PROD;
export const isAuthConfigured = true;
export const defaultAppPath = DEFAULT_APP_PATH;
export const loginPath = LOGIN_PATH;
export const setupPath = SETUP_PATH;

export function safeReturnTo(
  value: string | null | undefined,
  fallback = DEFAULT_APP_PATH,
): string {
  if (!value) return fallback;
  if (!value.startsWith("/")) return fallback;
  if (value.startsWith("//")) return fallback;
  if (
    value.startsWith(LOGIN_PATH) ||
    value.startsWith("/sign-in") ||
    value.startsWith("/sign-up") ||
    value.startsWith(SETUP_PATH)
  ) {
    return fallback;
  }
  return value;
}

export function buildLoginPath(returnTo: string): string {
  return `${LOGIN_PATH}?returnTo=${encodeURIComponent(safeReturnTo(returnTo))}`;
}

export function buildSetupPath(returnTo: string): string {
  return `${SETUP_PATH}?returnTo=${encodeURIComponent(safeReturnTo(returnTo))}`;
}

export function buildAuthEntryPath(returnTo: string): string {
  if (isLegacyDevAuthEnabled) {
    return buildSetupPath(returnTo);
  }
  return buildLoginPath(returnTo);
}

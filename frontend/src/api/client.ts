import { isLegacyDevAuthEnabled } from "@/lib/auth-mode";

const API_BASE = "/api";
const API_KEY_STORAGE_KEY = ["api", "key"].join("_");
const CSRF_COOKIE_NAME = "peos_csrf";

type RouteParam = string | number;
type RouteParams = Record<string, RouteParam>;
type PostOptions = {
  idempotencyKey?: string;
};
type LegacyAuth = {
  apiKey?: string;
};
const SAME_ORIGIN_CREDENTIALS: RequestCredentials = "same-origin";

class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

// ─── 401 redirect hook ────────────────────────────────────────
// Allows the app shell to register a callback that fires whenever
// any /api/* call returns 401. Defaulted to a no-op so test harnesses
// (and code that imports the client without a router) don't redirect.
type UnauthorizedHandler = () => void;
let unauthorizedHandler: UnauthorizedHandler = () => {};

export function setUnauthorizedHandler(handler: UnauthorizedHandler): void {
  unauthorizedHandler = handler;
}

export function clearUnauthorizedHandler(): void {
  unauthorizedHandler = () => {};
}

export async function getApiRequestHeaders(
  includeContentType = true,
  legacyAuth: LegacyAuth = {},
  includeCsrf = false,
): Promise<Record<string, string>> {
  const headers: Record<string, string> = {};
  if (includeContentType) {
    headers["Content-Type"] = "application/json";
  }
  if (isLegacyDevAuthEnabled) {
    const apiKey = legacyAuth.apiKey ?? sessionStorage.getItem(API_KEY_STORAGE_KEY);
    if (apiKey) {
      headers["X-API-Key"] = apiKey;
    }
  }
  if (includeCsrf) {
    const csrfToken = readCookie(CSRF_COOKIE_NAME);
    if (csrfToken) {
      headers["X-CSRF-Token"] = csrfToken;
    }
  }
  return headers;
}

function readCookie(name: string): string | null {
  if (typeof document === "undefined") {
    return null;
  }
  const prefix = `${encodeURIComponent(name)}=`;
  for (const part of document.cookie.split(";")) {
    const value = part.trim();
    if (value.startsWith(prefix)) {
      try {
        return decodeURIComponent(value.slice(prefix.length));
      } catch {
        return null;
      }
    }
  }
  return null;
}

async function getHeaders(includeContentType = true, includeCsrf = false): Promise<HeadersInit> {
  return getApiRequestHeaders(includeContentType, {}, includeCsrf);
}

function createIdempotencyKey(): string {
  if (
    typeof globalThis.crypto !== "undefined" &&
    typeof globalThis.crypto.randomUUID === "function"
  ) {
    return globalThis.crypto.randomUUID();
  }

  return `${Date.now().toString(36)}-${Math.random().toString(16).slice(2)}`;
}

async function getPostHeaders(options?: PostOptions): Promise<HeadersInit> {
  return {
    ...(await getHeaders(true, true)),
    "Idempotency-Key": options?.idempotencyKey ?? createIdempotencyKey(),
  };
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.text().catch(() => "Unknown error");
    // Try to extract FastAPI's detail field from JSON error bodies
    let message = body;
    try {
      const parsed = JSON.parse(body);
      if (parsed.detail) {
        message = typeof parsed.detail === "string" ? parsed.detail : JSON.stringify(parsed.detail);
      }
    } catch {
      // body is not JSON, use as-is
    }
    if (response.status === 401) {
      try {
        unauthorizedHandler();
      } catch {
        // never let a buggy handler break the rejected promise chain
      }
    }
    throw new ApiError(response.status, message);
  }
  // Handle 204 No Content (and other empty responses)
  if (response.status === 204 || response.headers.get("content-length") === "0") {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

function wrapFetch<T>(promise: Promise<Response>): Promise<T> {
  return promise
    .catch((err: unknown) => {
      if (err instanceof TypeError) {
        throw new ApiError(0, "Network error — check your connection");
      }
      throw err;
    })
    .then((r) => handleResponse<T>(r));
}

function substituteRouteParams(path: string, params?: RouteParams): string {
  if (!params) {
    return path;
  }

  let resolved = path;
  for (const [key, value] of Object.entries(params)) {
    resolved = resolved.replace(`{${key}}`, encodeURIComponent(String(value)));
  }
  return resolved;
}

export function apiPath(path: string, params?: RouteParams): string {
  const resolved = substituteRouteParams(path, params);
  return resolved.startsWith(API_BASE) ? resolved.slice(API_BASE.length) : resolved;
}

export function absolutePath(path: string, params?: RouteParams): string {
  return substituteRouteParams(path, params);
}

export const api = {
  async get<T>(
    path: string,
    params?: Record<string, string | number | boolean | undefined>,
  ): Promise<T> {
    const url = new URL(`${API_BASE}${path}`, window.location.origin);
    if (params) {
      for (const [key, value] of Object.entries(params)) {
        if (value !== undefined) {
          url.searchParams.set(key, String(value));
        }
      }
    }
    return wrapFetch<T>(
      fetch(url.toString(), {
        credentials: SAME_ORIGIN_CREDENTIALS,
        headers: await getHeaders(false),
      }),
    );
  },

  async post<T>(path: string, body?: unknown, options?: PostOptions): Promise<T> {
    return wrapFetch<T>(
      fetch(`${API_BASE}${path}`, {
        method: "POST",
        credentials: SAME_ORIGIN_CREDENTIALS,
        headers: await getPostHeaders(options),
        body: body != null ? JSON.stringify(body) : undefined,
      }),
    );
  },

  async put<T>(path: string, body?: unknown): Promise<T> {
    return wrapFetch<T>(
      fetch(`${API_BASE}${path}`, {
        method: "PUT",
        credentials: SAME_ORIGIN_CREDENTIALS,
        headers: await getHeaders(true, true),
        body: body != null ? JSON.stringify(body) : undefined,
      }),
    );
  },

  async patch<T>(path: string, body?: unknown): Promise<T> {
    return wrapFetch<T>(
      fetch(`${API_BASE}${path}`, {
        method: "PATCH",
        credentials: SAME_ORIGIN_CREDENTIALS,
        headers: await getHeaders(true, true),
        body: body != null ? JSON.stringify(body) : undefined,
      }),
    );
  },

  async delete<T = void>(path: string): Promise<T> {
    return wrapFetch<T>(
      fetch(`${API_BASE}${path}`, {
        method: "DELETE",
        credentials: SAME_ORIGIN_CREDENTIALS,
        headers: await getHeaders(false, true),
      }),
    );
  },
};

export function getWithQuery<T, TParams extends object>(
  path: string,
  params?: TParams,
): Promise<T> {
  if (!params) {
    return api.get<T>(path);
  }

  return api.get<T>(path, buildQueryParams(params));
}

// ─── Query Param Builder ─────────────────────────────────────
// Generic utility to convert a typed params object into a flat
// Record<string, string | number> suitable for query strings.
// Handles: null/undefined stripping, array → comma-join, boolean → 1.

export function buildQueryParams<T extends object>(params: T): Record<string, string | number> {
  const result: Record<string, string | number> = {};
  for (const [key, value] of Object.entries(params as Record<string, unknown>)) {
    if (value == null) continue;
    if (Array.isArray(value)) {
      if (value.length > 0) result[key] = value.join(",");
    } else if (typeof value === "boolean") {
      result[key] = value ? 1 : 0;
    } else if (typeof value === "string") {
      if (value) result[key] = value;
    } else if (typeof value === "number") {
      result[key] = value;
    }
  }
  return result;
}

export { ApiError };

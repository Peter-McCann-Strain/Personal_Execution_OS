import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  sessionStorage.clear();
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe("api client auth modes", () => {
  it("does not send browser API-key credentials unless legacy dev auth is enabled", async () => {
    vi.resetModules();
    vi.stubEnv("VITE_ALLOW_INSECURE_DEV_AUTH", "");
    sessionStorage.setItem("api_key", "sk-should-not-ship");

    const { getApiRequestHeaders } = await import("@/api/client");

    await expect(getApiRequestHeaders(false)).resolves.toEqual({});
  });

  it("sends the session API key only in explicit legacy dev auth mode", async () => {
    vi.resetModules();
    vi.stubEnv("VITE_ALLOW_INSECURE_DEV_AUTH", "true");
    sessionStorage.setItem("api_key", "sk-dev-only");

    const { getApiRequestHeaders } = await import("@/api/client");

    await expect(getApiRequestHeaders(false)).resolves.toEqual({
      "X-API-Key": "sk-dev-only",
    });
  });
});

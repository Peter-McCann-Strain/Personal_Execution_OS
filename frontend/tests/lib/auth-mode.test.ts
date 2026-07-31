import { afterEach, describe, expect, it, vi } from "vitest";

async function loadAuthMode(env: { allowInsecureDevAuth?: string }) {
  vi.resetModules();
  vi.stubEnv("VITE_ALLOW_INSECURE_DEV_AUTH", env.allowInsecureDevAuth ?? "");
  return import("@/lib/auth-mode");
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe("auth-mode", () => {
  it("uses a same-origin login page by default", async () => {
    const authMode = await loadAuthMode({});

    expect(authMode.isLegacyDevAuthEnabled).toBe(false);
    expect(authMode.isAuthConfigured).toBe(true);
    expect(authMode.buildAuthEntryPath("/email")).toBe("/login?returnTo=%2Femail");
  });

  it("uses the setup screen only in explicit legacy development mode", async () => {
    const authMode = await loadAuthMode({ allowInsecureDevAuth: "true" });

    expect(authMode.isLegacyDevAuthEnabled).toBe(true);
    expect(authMode.buildAuthEntryPath("/email")).toBe("/setup?returnTo=%2Femail");
  });

  it("rejects unsafe return targets", async () => {
    const authMode = await loadAuthMode({});

    expect(authMode.safeReturnTo("https://evil.example.com")).toBe("/dashboard");
    expect(authMode.safeReturnTo("//evil.example.com")).toBe("/dashboard");
    expect(authMode.safeReturnTo("/setup?returnTo=/email")).toBe("/dashboard");
    expect(authMode.safeReturnTo("/login?returnTo=/email")).toBe("/dashboard");
  });
});

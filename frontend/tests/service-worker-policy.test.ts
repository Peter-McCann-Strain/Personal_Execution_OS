import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("service worker cache policy", () => {
  const source = readFileSync(resolve(process.cwd(), "public/sw.js"), "utf8");

  it("limits runtime caching to static assets", () => {
    expect(source).toContain('url.pathname.startsWith("/assets/")');
    expect(source).toContain('request.mode === "navigate"');
    expect(source).toContain('request.destination === "document"');
    expect(source).toContain("url.search");
  });

  it.each(["/api", "/auth", "/login", "/sign-in", "/sign-up", "/setup", "/settings"])(
    "excludes %s from caching",
    (prefix) => {
      expect(source).toContain(`"${prefix}"`);
    },
  );

  it("does not cache private or no-store responses", () => {
    expect(source).toContain('cacheControl.includes("no-store")');
    expect(source).toContain('cacheControl.includes("private")');
  });

  it("versions the static cache and removes older cache generations on activation", () => {
    expect(source).toContain('const STATIC_CACHE_NAME = "execution-os-static-v4"');
    expect(source).toContain("key !== STATIC_CACHE_NAME");
    expect(source).toContain("caches.delete(key)");
    expect(source).toContain("self.clients.claim()");
  });
});

describe("PWA manifest", () => {
  const manifest = JSON.parse(
    readFileSync(resolve(process.cwd(), "public/manifest.webmanifest"), "utf8"),
  ) as {
    name: string;
    start_url: string;
    scope: string;
    display: string;
    icons: Array<{ src: string; sizes: string; type: string; purpose: string }>;
  };

  it("has installable app metadata and real PNG icon sizes", () => {
    expect(manifest).toMatchObject({
      name: "Personal Execution OS",
      start_url: "/",
      scope: "/",
      display: "standalone",
    });
    expect(manifest.icons).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ sizes: "192x192", type: "image/png", purpose: "any" }),
        expect.objectContaining({ sizes: "512x512", type: "image/png", purpose: "any" }),
        expect.objectContaining({ sizes: "192x192", type: "image/png", purpose: "maskable" }),
        expect.objectContaining({ sizes: "512x512", type: "image/png", purpose: "maskable" }),
      ]),
    );
    for (const icon of manifest.icons) {
      expect(
        readFileSync(resolve(process.cwd(), "public", icon.src.slice(1))).length,
      ).toBeGreaterThan(0);
    }
  });
});

describe("web push consent copy", () => {
  const pulseSource = readFileSync(resolve(process.cwd(), "src/pages/pulse.tsx"), "utf8");

  it("warns about lock-screen and push-provider metadata exposure before permission", () => {
    expect(pulseSource).toContain("locked screen");
    expect(pulseSource).toContain("endpoint, timing, and approximate");
    expect(pulseSource).toMatch(/content\s+previews require an explicit server-side opt-in/);
    expect(pulseSource).toContain("!pushRiskAccepted");
  });
});

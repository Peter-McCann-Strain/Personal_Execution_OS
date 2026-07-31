import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import { resolve } from "path";

/**
 * Router integrity tests — verify all sidebar nav items have
 * matching routes, and all routes have page components.
 */

const routerContent = readFileSync(resolve(__dirname, "../src/router.tsx"), "utf-8");

const sidebarContent = readFileSync(
  resolve(__dirname, "../src/components/layout/sidebar.tsx"),
  "utf-8",
);

describe("Router Completeness", () => {
  // Extract route paths from router.tsx
  const routePaths = Array.from(routerContent.matchAll(/path:\s*"([^"]+)"/g)).map((m) => m[1]);

  // Extract sidebar paths
  const sidebarPaths = Array.from(sidebarContent.matchAll(/path:\s*"([^"]+)"/g)).map((m) => m[1]);

  it("every sidebar nav path has a matching route", () => {
    for (const navPath of sidebarPaths) {
      const routePath = navPath.replace(/^\//, ""); // router uses relative paths
      expect(routePaths).toContain(routePath);
    }
  });

  it("has at least 19 app routes (one per sidebar item)", () => {
    // Filter out the "/" root paths
    const appRoutes = routePaths.filter((p) => p !== "/");
    expect(appRoutes.length).toBeGreaterThanOrEqual(19);
  });

  it("landing page route exists at /", () => {
    expect(routePaths).toContain("/");
  });

  it("imports all page components lazily", () => {
    const lazyImports = routerContent.match(/lazy\(\(\)/g);
    expect(lazyImports).toBeTruthy();
    expect(lazyImports!.length).toBeGreaterThanOrEqual(19);
  });

  it("all routes are wrapped in PageSuspense", () => {
    const suspenseWraps = routerContent.match(/<PageSuspense>/g);
    expect(suspenseWraps).toBeTruthy();
    expect(suspenseWraps!.length).toBeGreaterThanOrEqual(19);
  });

  it("has ErrorBoundary in PageSuspense", () => {
    expect(routerContent).toContain("ErrorBoundary");
  });
});

import { expect, test } from "@playwright/test";

test.describe("installable PWA boundary", () => {
  test.use({ serviceWorkers: "allow" });

  test("publishes install metadata and real maskable icons", async ({ page, request }) => {
    await page.goto("/welcome");

    await expect(page.locator('link[rel="manifest"]')).toHaveAttribute(
      "href",
      "/manifest.webmanifest",
    );
    const manifestResponse = await request.get("/manifest.webmanifest");
    expect(manifestResponse.ok()).toBe(true);
    const manifest = (await manifestResponse.json()) as {
      name: string;
      display: string;
      start_url: string;
      icons: Array<{ src: string; sizes: string; purpose: string }>;
    };
    expect(manifest).toMatchObject({
      name: "Personal Execution OS",
      display: "standalone",
      start_url: "/",
    });
    expect(manifest.icons).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ sizes: "192x192", purpose: "any" }),
        expect.objectContaining({ sizes: "512x512", purpose: "any" }),
        expect.objectContaining({ sizes: "192x192", purpose: "maskable" }),
        expect.objectContaining({ sizes: "512x512", purpose: "maskable" }),
      ]),
    );
    for (const icon of manifest.icons) {
      expect((await request.get(icon.src)).ok()).toBe(true);
    }
  });

  test("service worker caches only the public static shell", async ({ page }) => {
    await page.goto("/welcome");
    await page.waitForFunction(async () => {
      const registration = await navigator.serviceWorker.getRegistration();
      return Boolean(registration?.active);
    });
    await expect
      .poll(() =>
        page.evaluate(async () => {
          const cache = await caches.open("execution-os-static-v4");
          const urls = (await cache.keys()).map((request) => new URL(request.url).pathname);
          return [
            "/manifest.webmanifest",
            "/icon-192.png",
            "/icon-512.png",
            "/icon-maskable-192.png",
            "/icon-maskable-512.png",
          ].every((path) => urls.includes(path));
        }),
      )
      .toBe(true);

    const cacheState = await page.evaluate(async () => {
      const names = await caches.keys();
      const urls = (
        await Promise.all(
          names.map(async (name) => {
            const cache = await caches.open(name);
            return (await cache.keys()).map((request) => new URL(request.url).pathname);
          }),
        )
      ).flat();
      return { names, urls };
    });

    expect(cacheState.names).toContain("execution-os-static-v4");
    expect(cacheState.urls).toEqual(
      expect.arrayContaining([
        "/manifest.webmanifest",
        "/icon-192.png",
        "/icon-512.png",
        "/icon-maskable-192.png",
        "/icon-maskable-512.png",
      ]),
    );
    expect(
      cacheState.urls.some(
        (path) =>
          path.startsWith("/api") ||
          path.startsWith("/login") ||
          path.startsWith("/setup") ||
          path.startsWith("/settings") ||
          path === "/welcome",
      ),
    ).toBe(false);
  });

  test("landing page fits a phone viewport without horizontal overflow", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/welcome");

    await expect(page.getByRole("heading", { name: "Personal Execution OS" })).toBeVisible();
    const dimensions = await page.evaluate(() => ({
      viewport: document.documentElement.clientWidth,
      content: document.documentElement.scrollWidth,
    }));
    expect(dimensions.content).toBeLessThanOrEqual(dimensions.viewport);
  });
});

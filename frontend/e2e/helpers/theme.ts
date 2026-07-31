import type { Page } from "@playwright/test";

export type UITheme = "dark" | "light";

/**
 * Seed the Zustand persisted store and <html data-theme> attribute BEFORE
 * the app boots, so the first paint is already in the requested theme.
 * Avoids a flash that would confuse snapshot diffing.
 */
export async function setTheme(page: Page, theme: UITheme) {
  await page.addInitScript((t: UITheme) => {
    try {
      const payload = {
        state: {
          theme: t,
          sidebarCollapsed: false,
          commandPaletteOpen: false,
        },
        version: 0,
      };
      localStorage.setItem("assistant-app-store", JSON.stringify(payload));
      document.documentElement.setAttribute("data-theme", t);
    } catch {
      // addInitScript fires pre-app; localStorage should exist but guard anyway.
    }
  }, theme);
}

/**
 * Inject a CSS rule that hides any element marked as a dynamic time surface.
 * Pair with `data-dynamic-time` on components rendering relative/absolute
 * times so they don't thrash snapshot diffs.
 */
export async function maskDynamicRegions(page: Page) {
  await page.addStyleTag({
    content: `
      [data-dynamic-time],
      [data-testid="last-login"],
      [data-testid="agent-activity-timestamp"],
      [data-recharts-animation],
      .recharts-tooltip-wrapper {
        visibility: hidden !important;
      }
      *, *::before, *::after {
        animation-duration: 0ms !important;
        animation-delay: 0ms !important;
        transition-duration: 0ms !important;
        transition-delay: 0ms !important;
        caret-color: transparent !important;
      }
    `,
  });
}

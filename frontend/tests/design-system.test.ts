import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import { resolve } from "path";

/**
 * Design system structural tests — verify CSS custom properties,
 * theme completeness, and design token consistency.
 */

const cssContent = readFileSync(resolve(__dirname, "../src/index.css"), "utf-8");

describe("Design System CSS", () => {
  describe("Color tokens", () => {
    const requiredDarkTokens = [
      "--color-bg-base",
      "--color-bg-surface",
      "--color-bg-elevated",
      "--color-bg-overlay",
      "--color-bg-wash",
      "--color-fg-primary",
      "--color-fg-secondary",
      "--color-fg-tertiary",
      "--color-fg-disabled",
      "--color-fg-on-accent",
      "--color-border-default",
      "--color-border-subtle",
      "--color-border-strong",
      "--color-border-focus",
    ];

    for (const token of requiredDarkTokens) {
      it(`defines ${token} in dark mode`, () => {
        expect(cssContent).toContain(token);
      });
    }
  });

  describe("Semantic color scales", () => {
    const scales = ["success", "warning", "error", "info"];
    const levels = ["50", "100", "500", "600", "900"];

    for (const scale of scales) {
      for (const level of levels) {
        it(`defines --color-${scale}-${level}`, () => {
          expect(cssContent).toContain(`--color-${scale}-${level}`);
        });
      }
    }
  });

  describe("Agent colors", () => {
    const agents = ["diary", "memory", "research", "review", "project", "comms", "tools", "notif"];

    for (const agent of agents) {
      it(`defines --color-agent-${agent}`, () => {
        expect(cssContent).toContain(`--color-agent-${agent}`);
      });
    }
  });

  describe("Radius tokens", () => {
    const radii = ["sm", "md", "lg", "xl", "full"];
    for (const r of radii) {
      it(`defines --radius-${r}`, () => {
        expect(cssContent).toContain(`--radius-${r}`);
      });
    }
  });

  describe("Layout tokens", () => {
    it("defines sidebar width", () => {
      expect(cssContent).toContain("--sidebar-width");
    });
    it("defines collapsed sidebar width", () => {
      expect(cssContent).toContain("--sidebar-collapsed-width");
    });
    it("defines header height", () => {
      expect(cssContent).toContain("--header-height");
    });
  });

  describe("Light theme", () => {
    it("has a [data-theme='light'] section", () => {
      expect(cssContent).toContain('[data-theme="light"]');
    });

    it("overrides all bg tokens in light theme", () => {
      // Extract light theme block
      const lightMatch = cssContent.match(/\[data-theme="light"\]\s*\{([^}]+)\}/);
      expect(lightMatch).toBeTruthy();
      const lightBlock = lightMatch![1];
      expect(lightBlock).toContain("--color-bg-base");
      expect(lightBlock).toContain("--color-bg-surface");
      expect(lightBlock).toContain("--color-fg-primary");
      expect(lightBlock).toContain("--color-border-default");
    });
  });

  describe("Typography", () => {
    it("uses a local system sans-serif stack without external font requests", () => {
      expect(cssContent).toContain("ui-sans-serif");
      expect(cssContent).not.toContain("fonts.googleapis.com");
    });

    it("uses a local system monospace stack", () => {
      expect(cssContent).toContain("ui-monospace");
      expect(cssContent).toContain('"SFMono-Regular"');
    });

    it("enables font feature settings", () => {
      expect(cssContent).toContain("font-feature-settings");
    });
  });

  describe("Animations", () => {
    it("defines pulse-subtle keyframes", () => {
      expect(cssContent).toContain("@keyframes pulse-subtle");
    });

    it("defines agent-pulse keyframes", () => {
      expect(cssContent).toContain("@keyframes agent-pulse");
    });

    it("defines fade-in-up keyframes", () => {
      expect(cssContent).toContain("@keyframes fade-in-up");
    });

    it("defines stagger-in keyframes", () => {
      expect(cssContent).toContain("@keyframes stagger-in");
    });
  });

  describe("OKLCH color space", () => {
    it("uses oklch() for color definitions", () => {
      const oklchMatches = cssContent.match(/oklch\(/g);
      expect(oklchMatches).toBeTruthy();
      // Should have many oklch declarations
      expect(oklchMatches!.length).toBeGreaterThan(30);
    });
  });
});

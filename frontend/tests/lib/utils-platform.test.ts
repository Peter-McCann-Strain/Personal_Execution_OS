import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { cn, formatCurrency, formatRelativeTime, formatTokens, truncate } from "@/lib/utils";

describe("utils", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-04-07T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  test("cn merges class names and tailwind conflicts", () => {
    const hidden = false;
    expect(cn("p-2", hidden && "hidden", "text-sm", "p-4")).toBe("text-sm p-4");
  });

  test("formatRelativeTime handles seconds, minutes, hours, days, and older dates", () => {
    expect(formatRelativeTime(new Date("2026-04-07T11:59:45Z"))).toBe("just now");
    expect(formatRelativeTime(new Date("2026-04-07T11:10:00Z"))).toBe("50m ago");
    expect(formatRelativeTime(new Date("2026-04-07T09:00:00Z"))).toBe("3h ago");
    expect(formatRelativeTime(new Date("2026-04-05T12:00:00Z"))).toBe("2d ago");
    expect(formatRelativeTime("2026-03-01T12:00:00Z")).toBe(
      new Date("2026-03-01T12:00:00Z").toLocaleDateString(),
    );
  });

  test("formatCurrency, truncate, and formatTokens format values consistently", () => {
    expect(formatCurrency(12.34567)).toBe("$12.3457");
    expect(truncate("short", 10)).toBe("short");
    expect(truncate("truncate me", 5)).toBe("trun…");
    expect(formatTokens(999)).toBe("999");
    expect(formatTokens(15_500)).toBe("15.5K");
    expect(formatTokens(2_500_000)).toBe("2.5M");
  });
});

describe("platform", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  test("formats shortcuts for Mac platforms", async () => {
    vi.stubGlobal("navigator", { userAgent: "Macintosh" });
    const platform = await import("@/lib/platform");

    expect(platform.isMac).toBe(true);
    expect(platform.MOD_KEY).toBe("\u2318");
    expect(platform.formatShortcut("Mod+Alt+Shift+Ctrl+K")).toBe("\u2318+\u2325+\u21E7+\u2303+K");
  });

  test("formats shortcuts for non-Mac platforms", async () => {
    vi.stubGlobal("navigator", { userAgent: "Windows NT" });
    const platform = await import("@/lib/platform");

    expect(platform.isMac).toBe(false);
    expect(platform.MOD_KEY).toBe("Ctrl");
    expect(platform.formatShortcut("Mod+Alt+Shift+Ctrl+K")).toBe("Ctrl+Alt+Shift+Ctrl+K");
  });
});

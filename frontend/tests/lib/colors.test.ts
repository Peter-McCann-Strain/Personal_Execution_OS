import { describe, expect, it } from "vitest";
import {
  AVATAR_PALETTE,
  getPriorityColorClass,
  getProgressVariant,
  hashString,
  pickColor,
  tintedBg,
} from "@/lib/colors";

describe("colors", () => {
  it("hashes strings deterministically and never returns a negative value", () => {
    expect(hashString("project-alpha")).toBe(hashString("project-alpha"));
    expect(hashString("project-alpha")).toBeGreaterThanOrEqual(0);
  });

  it("picks deterministic palette colors and builds tinted backgrounds", () => {
    const color = pickColor("project-alpha");
    expect(AVATAR_PALETTE).toContain(color);
    expect(color).toBe(pickColor("project-alpha"));
    expect(tintedBg(color, 35)).toBe(`color-mix(in oklch, ${color} 35%, transparent)`);
  });

  it("maps priority and progress values to the expected display variants", () => {
    expect(getPriorityColorClass(2)).toBe("bg-[var(--color-error-500)]");
    expect(getPriorityColorClass(4)).toBe("bg-[var(--color-warning-500)]");
    expect(getPriorityColorClass(6)).toBe("bg-[var(--color-warning-900)]");
    expect(getPriorityColorClass(8)).toBe("bg-[var(--color-info-500)]");
    expect(getPriorityColorClass(10)).toBe("bg-[var(--color-fg-disabled)]");

    expect(getProgressVariant(80)).toBe("success");
    expect(getProgressVariant(50)).toBe("default");
    expect(getProgressVariant(25)).toBe("warning");
    expect(getProgressVariant(10)).toBe("error");
  });
});

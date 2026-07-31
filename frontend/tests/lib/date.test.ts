import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  formatActionTime,
  formatDeadline,
  formatInteractionDateTime,
  formatLatency,
  formatSlotTime,
  formatTime,
} from "@/lib/date";

describe("date utilities", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-04-07T12:00:00"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("formats times and slots using the local date values", () => {
    expect(formatTime("2026-04-07T09:30:00")).toBe("09:30");
    expect(formatSlotTime("2026-04-07T09:30:00")).toContain("09:30");
    expect(formatSlotTime("2026-04-07T09:30:00")).toContain("Apr");
  });

  it("formats activity timestamps for today and older dates", () => {
    expect(formatActionTime("2026-04-07T09:30:00")).toBe("09:30");
    expect(formatActionTime("2026-04-06T09:30:00")).toBe("6 Apr 09:30");
  });

  it("formats deadlines, interaction timestamps, and latencies", () => {
    expect(formatDeadline(null)).toBe("No deadline");
    expect(formatDeadline("2026-04-10T00:00:00")).toBe("10 Apr 2026");

    expect(formatInteractionDateTime("2026-04-07T14:30:00")).toEqual({
      date: "7 Apr 2026",
      time: "14:30",
    });

    expect(formatLatency(1500)).toBe("1.5s");
    expect(formatLatency(251)).toBe("251ms");
  });
});

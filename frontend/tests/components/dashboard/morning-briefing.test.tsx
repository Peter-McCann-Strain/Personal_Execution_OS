import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen } from "../../test-utils";
import { MorningBriefing } from "@/components/dashboard/morning-briefing";

const mocks = vi.hoisted(() => ({
  getMorningBriefing: vi.fn(),
}));

vi.mock("@/api/dashboard", () => ({
  getMorningBriefing: mocks.getMorningBriefing,
}));

describe("MorningBriefing", () => {
  beforeEach(() => {
    mocks.getMorningBriefing.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders a loading skeleton while briefing data is pending", () => {
    mocks.getMorningBriefing.mockReturnValue(new Promise(() => {}));

    const { container } = renderWithProviders(<MorningBriefing />);

    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });

  it("renders the error state when briefing data cannot be loaded", async () => {
    mocks.getMorningBriefing.mockRejectedValue(new Error("briefing failed"));

    renderWithProviders(<MorningBriefing />);

    expect(
      await screen.findByText("Unable to load briefing. Try refreshing the page."),
    ).toBeInTheDocument();
  });

  it("renders briefing content, notices, and prioritised notifications", async () => {
    mocks.getMorningBriefing.mockResolvedValue({
      greeting: {
        greeting: "Good morning",
        dateString: "Tuesday 7 April 2026",
        cognitiveLoad: "high",
        summary: "Focus on the highest leverage tasks.",
      },
      schedule: [
        {
          id: "event-1",
          summary: "Design review with the platform team",
          start: "2026-04-07T09:00:00Z",
          end: "2026-04-07T10:00:00Z",
          location: null,
          description: null,
          attendees: [],
        },
      ],
      notifications: [
        {
          id: "notification-1",
          message: "Critical follow-up due today",
          priority: "P0",
          category: "deadline",
          created_at: "2026-04-07T08:00:00Z",
          dismissed: false,
        },
        {
          id: "notification-2",
          message: "Background digest",
          priority: "P3",
          category: "digest",
          created_at: "2026-04-07T08:00:00Z",
          dismissed: false,
        },
      ],
      content: [
        {
          title: "How to tighten agent runtime policy boundaries",
          source: "Internal research",
          url: "https://example.com/runtime",
          relevance: 0.82,
        },
      ],
      status: "partial",
      notices: [
        {
          source: "calendar",
          status: "available",
          message: "Calendar connected",
        },
      ],
    });

    renderWithProviders(<MorningBriefing />);

    expect(await screen.findByText("Good morning")).toBeInTheDocument();
    expect(screen.getByText("Tuesday 7 April 2026")).toBeInTheDocument();
    expect(screen.getByText("7/10")).toBeInTheDocument();
    expect(screen.getByText(/Focus on the highest leverage tasks/)).toBeInTheDocument();
    expect(screen.getByText(/Design review with the platfo/)).toBeInTheDocument();
    expect(screen.getByText("(1h)")).toBeInTheDocument();
    expect(screen.getByText("Critical follow-up due today")).toBeInTheDocument();
    expect(screen.queryByText("Background digest")).not.toBeInTheDocument();
    expect(screen.getByText("82%")).toBeInTheDocument();
    expect(screen.getByText(/calendar:/i)).toBeInTheDocument();
    expect(screen.getByText("Calendar connected")).toBeInTheDocument();
  });

  it("renders empty-state copy when schedule, urgent notifications, and content are absent", async () => {
    mocks.getMorningBriefing.mockResolvedValue({
      greeting: {
        greeting: "Good afternoon",
        dateString: "Tuesday 7 April 2026",
        cognitiveLoad: 2,
        summary: "",
      },
      schedule: [],
      notifications: [],
      content: [],
      status: "ready",
      notices: [],
    });

    renderWithProviders(<MorningBriefing />);

    expect(await screen.findByText("Good afternoon")).toBeInTheDocument();
    expect(screen.getByText("No events scheduled. A clear day for deep work.")).toBeInTheDocument();
    expect(screen.getByText("All clear. No urgent notifications.")).toBeInTheDocument();
    expect(screen.getByText("No curated content available.")).toBeInTheDocument();
  });

  it.each([
    ["2026-04-07T07:30:00Z", "Good morning"],
    ["2026-04-07T13:30:00Z", "Good afternoon"],
    ["2026-04-07T18:30:00Z", "Good evening"],
    ["2026-04-07T22:30:00Z", "Working late"],
  ])("falls back to the correct greeting for %s", async (time, expected) => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(time));

    mocks.getMorningBriefing.mockResolvedValue({
      greeting: {
        greeting: "",
        dateString: "Tuesday 7 April 2026",
        cognitiveLoad: 2,
        summary: "",
      },
      schedule: [
        {
          id: "event-1",
          summary: "Focus sprint",
          start: "2026-04-07T09:00:00Z",
          end: "2026-04-07T09:30:00Z",
          location: null,
          description: null,
          attendees: [],
        },
      ],
      notifications: [],
      content: [],
      status: "ready",
      notices: [],
    });

    renderWithProviders(<MorningBriefing />);

    expect(await screen.findByText(expected)).toBeInTheDocument();
    expect(screen.getByText("2/10")).toBeInTheDocument();
    expect(screen.getByText("(30m)")).toBeInTheDocument();
  });

  it("renders cognitive load from string inputs", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-04-07T10:00:00Z"));

    mocks.getMorningBriefing.mockResolvedValue({
      greeting: {
        greeting: "",
        dateString: "Tuesday 7 April 2026",
        cognitiveLoad: "critical",
        summary: "",
      },
      schedule: [],
      notifications: [],
      content: [],
      status: "ready",
      notices: [],
    });

    const { rerender } = renderWithProviders(<MorningBriefing />);

    expect(await screen.findByText("Good morning")).toBeInTheDocument();
    expect(screen.getByText("9/10")).toBeInTheDocument();
    rerender(<MorningBriefing />);
    expect(screen.getByText("9/10")).toBeInTheDocument();
  });

  it("hides the cognitive load bar when the value cannot be parsed", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-04-07T22:00:00Z"));

    mocks.getMorningBriefing.mockResolvedValue({
      greeting: {
        greeting: "",
        dateString: "Tuesday 7 April 2026",
        cognitiveLoad: "not-a-number",
        summary: "",
      },
      schedule: [],
      notifications: [],
      content: [],
      status: "ready",
      notices: [],
    });

    renderWithProviders(<MorningBriefing />);

    expect(await screen.findByText("Working late")).toBeInTheDocument();
    expect(screen.queryByText(/Cognitive Load:/)).not.toBeInTheDocument();
  });
});

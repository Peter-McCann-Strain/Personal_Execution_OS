import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen } from "../../test-utils";
import { WeeklyReviewDetail } from "@/components/reviews/weekly-review-detail";
import type { WeeklyReview } from "@/types";

vi.mock("recharts", async () => {
  const { rechartsMock } = await import("../../recharts-mock");
  return rechartsMock;
});

function createReview(overrides: Partial<WeeklyReview> = {}): WeeklyReview {
  return {
    id: "review-1",
    period: "2026-W14",
    accomplishments: ["Shipped the SSE contract", "Added operator readiness"],
    mood_summary: "Calm and focused",
    average_mood: 7,
    goal_progress: [
      { title: "Runtime", progress: 80, status: "active" },
      { title: "Coverage", progress: 40, status: "at_risk" },
    ],
    open_commitments: [
      { action: "Review deploy logs", status: "completed" },
      { action: "Clear flaky tests", status: "OVERDUE" },
    ],
    relationship_alerts: [],
    patterns_noticed: ["Productivity improved when mornings stayed quiet"],
    recommendations: ["Keep deep work before noon", "Trim noisy dashboards"],
    key_insight: "Smoother routing reduced operational friction",
    created_at: "2026-04-07T09:00:00Z",
    ...overrides,
  };
}

describe("WeeklyReviewDetail", () => {
  it("renders the detail sections, charts, progress, commitments, patterns, and recommendations", () => {
    renderWithProviders(
      <WeeklyReviewDetail
        review={createReview()}
        previousMood={6}
        moodChartData={[
          { day: "Mon", mood: 6, energy: 7 },
          { day: "Tue", mood: 7, energy: 8 },
        ]}
      />,
    );

    expect(screen.getByRole("heading", { name: "Weekly Review: 2026-W14" })).toBeInTheDocument();
    expect(screen.getByText("Calm and focused")).toBeInTheDocument();
    expect(screen.getByText("Accomplishments")).toBeInTheDocument();
    expect(screen.getByText("Shipped the SSE contract")).toBeInTheDocument();
    expect(screen.getByText("Mood & Energy")).toBeInTheDocument();
    expect(screen.getByText("Runtime")).toBeInTheDocument();
    expect(screen.getByText("OVERDUE")).toBeInTheDocument();
    expect(
      screen.getByText(/Productivity improved when mornings stayed quiet/),
    ).toBeInTheDocument();
    expect(screen.getByText("Keep deep work before noon")).toBeInTheDocument();
    expect(screen.getByText(/Smoother routing reduced operational friction/)).toBeInTheDocument();
  });

  it("omits optional sections when the review data is sparse", () => {
    renderWithProviders(
      <WeeklyReviewDetail
        review={createReview({
          accomplishments: [],
          average_mood: null,
          mood_summary: null,
          goal_progress: [],
          open_commitments: [],
          patterns_noticed: [],
          recommendations: [],
          key_insight: null,
        })}
        moodChartData={[]}
      />,
    );

    expect(screen.queryByText("Accomplishments")).not.toBeInTheDocument();
    expect(screen.queryByText("Mood & Energy")).not.toBeInTheDocument();
    expect(screen.queryByText("Goal Progress")).not.toBeInTheDocument();
    expect(screen.queryByText("Open Commitments")).not.toBeInTheDocument();
    expect(screen.queryByText("Patterns Detected")).not.toBeInTheDocument();
    expect(screen.queryByText("Recommendations")).not.toBeInTheDocument();
  });

  it("renders downward mood movement and fallback pattern icons", () => {
    renderWithProviders(
      <WeeklyReviewDetail
        review={createReview({
          average_mood: 5,
          mood_summary: null,
          accomplishments: ["Finished the sprint review"],
          goal_progress: [{ title: "Operational risk", progress: 20, status: "planned" }],
          open_commitments: [{ action: "Review deploy logs", status: "pending" }],
          patterns_noticed: ["Kept things intentionally simple"],
          recommendations: ["Keep doing less"],
          key_insight: null,
        })}
        previousMood={7}
        moodChartData={[]}
      />,
    );

    expect(screen.getByText("5.0")).toBeInTheDocument();
    expect(document.querySelector(".lucide-arrow-down")).not.toBeNull();
    expect(screen.getByText("planned")).toBeInTheDocument();
    expect(screen.getByText("pending")).toBeInTheDocument();
    expect(screen.getByText("Kept things intentionally simple")).toBeInTheDocument();
    expect(document.querySelector(".lucide-lightbulb")).not.toBeNull();
  });

  it("renders the neutral mood arrow when there is no previous mood and supports collapsible chart-less detail", () => {
    renderWithProviders(
      <WeeklyReviewDetail
        review={createReview({
          average_mood: 6,
          mood_summary: null,
          accomplishments: [],
          goal_progress: [],
          open_commitments: [],
          patterns_noticed: [],
          recommendations: [],
          key_insight: null,
        })}
        moodChartData={[]}
      />,
    );

    expect(document.querySelector(".lucide-arrow-right")).not.toBeNull();
    expect(screen.queryByText("Accomplishments")).not.toBeInTheDocument();
    expect(screen.queryByText("Mood & Energy")).not.toBeInTheDocument();
  });

  it("renders the neutral mood arrow when the trend is unchanged", () => {
    renderWithProviders(
      <WeeklyReviewDetail
        review={createReview({
          average_mood: 7,
          mood_summary: null,
          accomplishments: [],
          goal_progress: [],
          open_commitments: [],
          patterns_noticed: [],
          recommendations: [],
          key_insight: null,
        })}
        previousMood={7}
        moodChartData={[]}
      />,
    );

    expect(document.querySelector(".lucide-arrow-right")).not.toBeNull();
  });
});

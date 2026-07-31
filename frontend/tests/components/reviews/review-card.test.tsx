import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen } from "../../test-utils";
import { MoodTrend, ReviewCard } from "@/components/reviews/review-card";
import type { WeeklyReview } from "@/types";

function createReview(overrides: Partial<WeeklyReview> = {}): WeeklyReview {
  return {
    id: "review-1",
    period: "2026-W14",
    accomplishments: ["Shipped the SSE contract"],
    mood_summary: "Steady",
    average_mood: 7,
    goal_progress: [],
    open_commitments: [],
    relationship_alerts: [],
    patterns_noticed: ["Better focus"],
    recommendations: ["Protect mornings"],
    key_insight: "Reducing context switching improved output",
    created_at: "2026-04-07T09:00:00Z",
    ...overrides,
  };
}

describe("ReviewCard", () => {
  it("renders review metrics, insight preview, and forwards clicks", () => {
    const onClick = vi.fn();

    renderWithProviders(<ReviewCard review={createReview()} previousMood={6} onClick={onClick} />);

    expect(screen.getByText("WEEKLY")).toBeInTheDocument();
    expect(screen.getByText("2026-W14")).toBeInTheDocument();
    expect(screen.getByText("7.0")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText(/Reducing context switching improved output/)).toBeInTheDocument();

    screen.getByText("2026-W14").click();
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("renders the neutral trend when previous mood is missing or unchanged", () => {
    const { rerender } = renderWithProviders(<MoodTrend current={7} previous={undefined} />);
    expect(document.querySelector(".lucide-arrow-right")).not.toBeNull();

    rerender(<MoodTrend current={7} previous={7} />);
    expect(document.querySelector(".lucide-arrow-right")).not.toBeNull();
  });

  it("renders downward trend, hides missing insight, and ignores null mood", () => {
    const onClick = vi.fn();

    renderWithProviders(
      <ReviewCard
        review={createReview({
          average_mood: 5.5,
          key_insight: null,
        })}
        previousMood={7}
        onClick={onClick}
      />,
    );

    expect(screen.getByText("5.5")).toBeInTheDocument();
    expect(
      screen.queryByText(/Reducing context switching improved output/),
    ).not.toBeInTheDocument();
    expect(document.querySelector(".lucide-arrow-down")).not.toBeNull();
  });

  it("returns nothing when the mood trend has no current value", () => {
    const { container } = renderWithProviders(<MoodTrend current={null} previous={7} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("renders a zero accomplishment count when none are present", () => {
    renderWithProviders(
      <ReviewCard
        review={createReview({
          accomplishments: [],
          key_insight: null,
        })}
        previousMood={6}
      />,
    );

    expect(screen.getByText("0")).toBeInTheDocument();
  });
});

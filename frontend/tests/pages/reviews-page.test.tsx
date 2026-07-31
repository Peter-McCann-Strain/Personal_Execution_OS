import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent, waitFor } from "../test-utils";
import { createPaginatedResponse } from "../factories";
import { ReviewsPage } from "@/pages/reviews";
import type { WeeklyReview } from "@/types";

const mocks = vi.hoisted(() => ({
  generateReview: vi.fn(),
  getReviews: vi.fn(),
}));

vi.mock("@/api/reviews", () => ({
  generateReview: mocks.generateReview,
  getReviews: mocks.getReviews,
}));

vi.mock("@/components/ui/page-transition", () => ({
  PageTransition: ({ children }: { children: React.ReactNode }) => children,
}));

vi.mock("@/components/ui/page-header", () => ({
  PageHeader: ({
    children,
    subtitle,
    title,
  }: {
    children?: React.ReactNode;
    subtitle: string;
    title: string;
  }) => (
    <div>
      <h1>{title}</h1>
      <p>{subtitle}</p>
      <div>{children}</div>
    </div>
  ),
}));

vi.mock("@/components/ui/page-error", () => ({
  PageError: ({ message, onRetry }: { message: string; onRetry?: () => void }) => (
    <div>
      <div>Page Error: {message}</div>
      {onRetry ? (
        <button type="button" onClick={onRetry}>
          Retry
        </button>
      ) : null}
    </div>
  ),
}));

vi.mock("@/components/reviews/review-card", () => ({
  ReviewCard: ({
    onClick,
    previousMood,
    review,
  }: {
    onClick: () => void;
    previousMood?: number | null;
    review: WeeklyReview;
  }) => (
    <div>
      <div>{review.period}</div>
      <div>Previous mood: {previousMood ?? "none"}</div>
      <button type="button" onClick={onClick}>
        Open {review.id}
      </button>
    </div>
  ),
}));

vi.mock("@/components/reviews/weekly-review-detail", () => ({
  WeeklyReviewDetail: ({
    moodChartData,
    previousMood,
    review,
  }: {
    moodChartData: Array<{ day: string }>;
    previousMood?: number | null;
    review: WeeklyReview;
  }) => (
    <div>
      <div>Review Detail: {review.period}</div>
      <div>Previous review mood: {previousMood ?? "none"}</div>
      <div>Mood chart points: {moodChartData.length}</div>
    </div>
  ),
}));

function createReview(overrides: Partial<WeeklyReview> = {}): WeeklyReview {
  return {
    id: "review-1",
    period: "2026-W14",
    accomplishments: ["Shipped monitoring improvements"],
    mood_summary: "Steady week",
    average_mood: 7,
    goal_progress: [],
    open_commitments: [],
    relationship_alerts: [],
    patterns_noticed: ["Good focus"],
    recommendations: ["Keep the pace"],
    key_insight: "Fewer interruptions improved quality",
    created_at: "2026-04-07T09:00:00Z",
    ...overrides,
  };
}

describe("ReviewsPage", () => {
  beforeEach(() => {
    mocks.generateReview.mockReset();
    mocks.generateReview.mockResolvedValue(createReview());
    mocks.getReviews.mockReset();
  });

  it("renders review cards and triggers review generation", async () => {
    const user = userEvent.setup();
    const reviews = [
      createReview(),
      createReview({ id: "review-2", period: "2026-W13", average_mood: 6 }),
    ];
    mocks.getReviews.mockResolvedValue(
      createPaginatedResponse(reviews, { total: 2, page_size: 20 }),
    );

    renderWithProviders(<ReviewsPage />);

    expect(await screen.findByRole("heading", { name: "Reviews" })).toBeInTheDocument();
    expect(await screen.findByText("2026-W14")).toBeInTheDocument();
    expect(screen.getByText("Previous mood: 6")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Generate Review" }));
    await waitFor(() => {
      expect(mocks.generateReview).toHaveBeenCalledWith("weekly");
    });
  });

  it("refetches reviews when the type filter changes", async () => {
    const user = userEvent.setup();
    mocks.getReviews.mockResolvedValue(
      createPaginatedResponse([createReview()], { total: 1, page_size: 20 }),
    );

    renderWithProviders(<ReviewsPage />);

    expect(await screen.findByText("2026-W14")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Quarterly" }));

    await waitFor(() => {
      expect(mocks.getReviews).toHaveBeenLastCalledWith({
        limit: 20,
        order: "desc",
        review_type: "quarterly",
        sort: "created_at",
      });
    });
  });

  it("opens the review detail view and preserves derived chart data", async () => {
    const user = userEvent.setup();
    const reviews = [
      createReview(),
      createReview({ id: "review-2", period: "2026-W13", average_mood: 6 }),
    ];
    mocks.getReviews.mockResolvedValue(
      createPaginatedResponse(reviews, { total: 2, page_size: 20 }),
    );

    renderWithProviders(<ReviewsPage />);

    expect(await screen.findByText("2026-W14")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Open review-1" }));

    expect(await screen.findByText("Review Detail: 2026-W14")).toBeInTheDocument();
    expect(screen.getByText("Previous review mood: 6")).toBeInTheDocument();
    expect(screen.getByText("Mood chart points: 7")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "All Reviews" }));
    expect(await screen.findByText("2026-W14")).toBeInTheDocument();
  });

  it("renders the empty state and allows generating a review from it", async () => {
    const user = userEvent.setup();
    mocks.getReviews.mockResolvedValue(createPaginatedResponse([], { total: 0, page_size: 20 }));

    renderWithProviders(<ReviewsPage />);

    expect(await screen.findByText("No reviews yet")).toBeInTheDocument();

    await user.click(screen.getAllByRole("button", { name: "Generate Review" })[1]);
    await waitFor(() => {
      expect(mocks.generateReview).toHaveBeenCalledWith("weekly");
    });
  });

  it("shows the generating state while a review request is pending", async () => {
    const user = userEvent.setup();
    const reviews = [
      createReview(),
      createReview({ id: "review-2", period: "2026-W13", average_mood: 6 }),
    ];
    let resolveGenerate!: (value: WeeklyReview) => void;
    const generatePromise = new Promise<WeeklyReview>((resolve) => {
      resolveGenerate = resolve;
    });

    mocks.getReviews.mockResolvedValue(
      createPaginatedResponse(reviews, { total: 2, page_size: 20 }),
    );
    mocks.generateReview.mockReturnValue(generatePromise);

    renderWithProviders(<ReviewsPage />);

    expect(await screen.findByText("2026-W14")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Generate Review" }));
    expect(await screen.findByText("Generating...")).toBeInTheDocument();

    resolveGenerate(createReview());
    await waitFor(() => {
      expect(mocks.generateReview).toHaveBeenCalledWith("weekly");
    });
  });

  it("renders the review detail fallback when there is no previous review and no average mood", async () => {
    const user = userEvent.setup();
    mocks.getReviews.mockResolvedValue(
      createPaginatedResponse([createReview({ average_mood: null })], { total: 1, page_size: 20 }),
    );

    renderWithProviders(<ReviewsPage />);

    expect(await screen.findByText("2026-W14")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Open review-1" }));

    expect(await screen.findByText("Review Detail: 2026-W14")).toBeInTheDocument();
    expect(screen.getByText("Previous review mood: none")).toBeInTheDocument();
    expect(screen.getByText("Mood chart points: 7")).toBeInTheDocument();
  });

  it("renders the page error when the reviews query fails", async () => {
    const user = userEvent.setup();
    mocks.getReviews.mockRejectedValue({});

    renderWithProviders(<ReviewsPage />);

    expect(await screen.findByText("Page Error: Failed to load reviews")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => {
      expect(mocks.getReviews).toHaveBeenCalledTimes(2);
    });
  });
});

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent } from "../../test-utils";
import { DecisionCard, StarRating } from "@/components/decisions/decision-card";
import type { Decision } from "@/api/decisions";

function createDecision(overrides: Partial<Decision> = {}): Decision {
  return {
    id: "decision-1",
    title: "Choose hosting provider",
    context: "Infra review",
    options_considered: ["Option A", "Option B", "Option C", "Option D", "Option E"],
    decision_made: "Use provider A",
    reasoning: "Latency and support",
    expected_outcome: "Simpler operations",
    actual_outcome: null,
    outcome_rating: 4,
    tags: ["infra", "platform"],
    review_date: "2026-04-01",
    status: "pending_review",
    created_at: "2026-04-01T09:00:00Z",
    updated_at: "2026-04-01T09:00:00Z",
    ...overrides,
  };
}

describe("DecisionCard", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-04-08T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the status, overdue review date, chips, and forwards clicks", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();

    renderWithProviders(<DecisionCard decision={createDecision()} onClick={onClick} />);

    expect(screen.getByText("Pending Review")).toBeInTheDocument();
    expect(screen.getByText("Choose hosting provider")).toBeInTheDocument();
    expect(screen.getByText(/Overdue:/)).toBeInTheDocument();
    expect(screen.getAllByText(/Apr 1, 2026/)).toHaveLength(2);
    expect(screen.getByText("Option A")).toBeInTheDocument();
    expect(screen.getByText("Option D")).toBeInTheDocument();
    expect(screen.getByText("+1 more")).toBeInTheDocument();
    expect(screen.getByText("infra")).toBeInTheDocument();
    expect(screen.getByText("platform")).toBeInTheDocument();

    await user.click(screen.getByText("Choose hosting provider"));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("renders reviewed decisions without review metadata", () => {
    const { container } = renderWithProviders(
      <DecisionCard
        decision={createDecision({
          status: "reviewed",
          review_date: null,
          options_considered: [],
          outcome_rating: null,
        })}
      />,
    );

    expect(screen.getByText("Reviewed")).toBeInTheDocument();
    expect(screen.queryByText(/Review:/)).not.toBeInTheDocument();
    expect(container.querySelectorAll("svg").length).toBeGreaterThan(0);
  });

  it("renders archived decisions without optional chips or rating and shows a non-overdue review date", () => {
    renderWithProviders(
      <DecisionCard
        decision={createDecision({
          status: "archived",
          review_date: "2026-04-20",
          options_considered: [],
          tags: [],
          outcome_rating: null,
        })}
      />,
    );

    expect(screen.getByText("Archived")).toBeInTheDocument();
    expect(screen.getByText(/Review:/)).toBeInTheDocument();
    expect(screen.getByText(/Apr 20, 2026/)).toBeInTheDocument();
    expect(screen.queryByText("+1 more")).not.toBeInTheDocument();
    expect(screen.queryByText("infra")).not.toBeInTheDocument();
    expect(screen.queryByText("platform")).not.toBeInTheDocument();
  });
});

describe("StarRating", () => {
  it("renders the requested number of stars", () => {
    const { container } = renderWithProviders(<StarRating rating={3} max={4} />);

    expect(container.querySelectorAll("svg")).toHaveLength(4);
  });
});

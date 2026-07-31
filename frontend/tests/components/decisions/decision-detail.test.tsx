import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent, waitFor } from "../../test-utils";
import { DecisionDetail } from "@/components/decisions/decision-detail";
import type { Decision } from "@/api/decisions";

const mocks = vi.hoisted(() => ({
  recordOutcome: vi.fn(),
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: {
    error: mocks.toastError,
    success: mocks.toastSuccess,
  },
}));

vi.mock("@/api/decisions", () => ({
  recordOutcome: mocks.recordOutcome,
}));

function createDecision(overrides: Partial<Decision> = {}): Decision {
  return {
    id: "decision-1",
    title: "Choose hosting provider",
    context: "Infra review",
    options_considered: ["Option A", "Option B"],
    decision_made: "Use provider A",
    reasoning: "Latency and support",
    expected_outcome: "Simpler operations",
    actual_outcome: null,
    outcome_rating: null,
    tags: ["infra"],
    review_date: "2026-04-01",
    status: "pending_review",
    created_at: "2026-04-01T09:00:00Z",
    updated_at: "2026-04-02T09:00:00Z",
    ...overrides,
  };
}

describe("DecisionDetail", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-04-08T12:00:00Z"));
    mocks.recordOutcome.mockReset();
    mocks.toastError.mockReset();
    mocks.toastSuccess.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the decision detail and records an outcome", async () => {
    const user = userEvent.setup();
    const onBack = vi.fn();
    mocks.recordOutcome.mockResolvedValue(
      createDecision({
        actual_outcome: "Infrastructure stayed stable",
        outcome_rating: 4,
        status: "reviewed",
      }),
    );

    renderWithProviders(<DecisionDetail decision={createDecision()} onBack={onBack} />);

    expect(screen.getByRole("heading", { name: "Choose hosting provider" })).toBeInTheDocument();
    expect(screen.getByText("Infra review")).toBeInTheDocument();
    expect(screen.getByText("Option A")).toBeInTheDocument();
    expect(screen.getByText("Use provider A")).toBeInTheDocument();
    expect(screen.getByText("Latency and support")).toBeInTheDocument();
    expect(screen.getByText("Simpler operations")).toBeInTheDocument();
    expect(screen.getByText("infra")).toBeInTheDocument();
    expect(screen.getByText("Record Outcome")).toBeInTheDocument();

    await user.type(
      screen.getByPlaceholderText("Describe the actual outcome of this decision..."),
      "Infrastructure stayed stable",
    );
    await user.click(screen.getByRole("button", { name: "Rate 4 of 5" }));
    await user.click(screen.getByRole("button", { name: "Save Outcome" }));

    await waitFor(() => {
      expect(mocks.recordOutcome).toHaveBeenCalledWith("decision-1", {
        actual_outcome: "Infrastructure stayed stable",
        outcome_rating: 4,
      });
    });
    expect(mocks.toastSuccess).toHaveBeenCalledWith("Outcome recorded successfully");
    expect(screen.queryByText("Record Outcome")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "All Decisions" }));
    expect(onBack).toHaveBeenCalledTimes(1);
  }, 15000);

  it("renders recorded outcomes without the review form", () => {
    renderWithProviders(
      <DecisionDetail
        decision={createDecision({
          status: "reviewed",
          actual_outcome: "Migration went well",
          outcome_rating: 5,
          review_date: "2026-04-20",
        })}
        onBack={vi.fn()}
      />,
    );

    expect(screen.getByText("Actual Outcome")).toBeInTheDocument();
    expect(screen.getByText("Migration went well")).toBeInTheDocument();
    expect(screen.getByText("Outcome rating:")).toBeInTheDocument();
    expect(screen.getByText(/Review:/)).toBeInTheDocument();
    expect(screen.queryByText("Record Outcome")).not.toBeInTheDocument();
  });

  it("hides the review form when a pending decision already has an outcome and omits optional sections", () => {
    renderWithProviders(
      <DecisionDetail
        decision={createDecision({
          context: "",
          options_considered: [],
          reasoning: "",
          expected_outcome: "",
          actual_outcome: "Rolled out cleanly",
          outcome_rating: null,
          tags: [],
          review_date: null,
          updated_at: "2026-04-01T09:00:00Z",
        })}
        onBack={vi.fn()}
      />,
    );

    expect(screen.getByText("Actual Outcome")).toBeInTheDocument();
    expect(screen.getByText("Rolled out cleanly")).toBeInTheDocument();
    expect(screen.queryByText("Record Outcome")).not.toBeInTheDocument();
    expect(screen.queryByText("Context")).not.toBeInTheDocument();
    expect(screen.queryByText("Options Considered")).not.toBeInTheDocument();
    expect(screen.queryByText("Reasoning")).not.toBeInTheDocument();
    expect(screen.queryByText("Expected Outcome")).not.toBeInTheDocument();
    expect(screen.queryByText("Tags")).not.toBeInTheDocument();
    expect(screen.queryByText("Updated")).not.toBeInTheDocument();
  });

  it("shows an error toast when recording an outcome fails", async () => {
    const user = userEvent.setup();
    mocks.recordOutcome.mockRejectedValueOnce(new Error("record failed"));

    renderWithProviders(<DecisionDetail decision={createDecision()} onBack={vi.fn()} />);

    await user.type(
      screen.getByPlaceholderText("Describe the actual outcome of this decision..."),
      "Launch slipped by a week",
    );
    await user.click(screen.getByRole("button", { name: "Save Outcome" }));

    await waitFor(() => {
      expect(mocks.recordOutcome).toHaveBeenCalledWith("decision-1", {
        actual_outcome: "Launch slipped by a week",
        outcome_rating: undefined,
      });
    });
    expect(mocks.toastError).toHaveBeenCalledWith("Failed to record outcome");
    expect(screen.getByText("Record Outcome")).toBeInTheDocument();
  }, 15000);
});

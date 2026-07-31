import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent, waitFor } from "../test-utils";
import { createPaginatedResponse } from "../factories";
import { DecisionsPage } from "@/pages/decisions";
import type { Decision } from "@/api/decisions";

const mocks = vi.hoisted(() => ({
  getDecisions: vi.fn(),
  getDecisionsDueReview: vi.fn(),
}));

vi.mock("@/api/decisions", () => ({
  getDecisions: mocks.getDecisions,
  getDecisionsDueReview: mocks.getDecisionsDueReview,
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
  PageError: ({ message }: { message: string }) => <div>Page Error: {message}</div>,
}));

vi.mock("@/components/ui/skeleton", () => ({
  Skeleton: () => <div data-testid="skeleton" />,
}));

vi.mock("@/components/decisions/decision-card", () => ({
  DecisionCard: ({ decision, onClick }: { decision: Decision; onClick: () => void }) => (
    <div>
      <span>{decision.title}</span>
      <button type="button" onClick={onClick}>
        Open {decision.id}
      </button>
    </div>
  ),
}));

vi.mock("@/components/decisions/decision-detail", () => ({
  DecisionDetail: ({ decision, onBack }: { decision: Decision; onBack: () => void }) => (
    <div>
      <div>Decision Detail: {decision.title}</div>
      <button type="button" onClick={onBack}>
        Back to decisions
      </button>
    </div>
  ),
}));

vi.mock("@/components/decisions/create-decision-modal", () => ({
  CreateDecisionModal: ({
    open,
    onOpenChange,
  }: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
  }) => (
    <div>
      <div>{open ? "Create Decision Modal Open" : "Create Decision Modal Closed"}</div>
      <button type="button" onClick={() => onOpenChange(false)}>
        Close decision modal
      </button>
    </div>
  ),
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
    review_date: "2026-04-10",
    status: "pending_review",
    created_at: "2026-04-01T09:00:00Z",
    updated_at: "2026-04-01T09:00:00Z",
    ...overrides,
  };
}

describe("DecisionsPage", () => {
  beforeEach(() => {
    mocks.getDecisions.mockReset();
    mocks.getDecisionsDueReview.mockReset();
  });

  it("surfaces due reviews, supports pagination, and resets filters correctly", async () => {
    const user = userEvent.setup();
    const pendingDecision = createDecision();
    const reviewedDecision = createDecision({
      id: "decision-2",
      title: "Review hiring plan",
      status: "reviewed",
    });

    mocks.getDecisions.mockImplementation(
      async (params?: { limit?: number; offset?: number; status?: string }) => {
        if (params?.status === "pending_review") {
          return createPaginatedResponse([pendingDecision], {
            total: 1,
            has_more: false,
            page_size: 25,
          });
        }
        if (params?.offset === 25) {
          return createPaginatedResponse([reviewedDecision], {
            total: 2,
            has_more: false,
            page_size: 25,
            page: 2,
          });
        }
        return createPaginatedResponse([reviewedDecision], {
          total: 2,
          has_more: true,
          page_size: 25,
        });
      },
    );
    mocks.getDecisionsDueReview.mockResolvedValue([pendingDecision]);

    renderWithProviders(<DecisionsPage />);

    expect(await screen.findByText("1 decision due for review")).toBeInTheDocument();
    expect(screen.getByText("Review hiring plan")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Load More" }));
    await waitFor(() => {
      expect(mocks.getDecisions).toHaveBeenLastCalledWith({ limit: 25, offset: 25 });
    });

    await user.click(screen.getByRole("button", { name: "Review Now" }));
    await waitFor(() => {
      expect(mocks.getDecisions).toHaveBeenLastCalledWith({
        limit: 25,
        offset: 0,
        status: "pending_review",
      });
    });
  }, 15000);

  it("switches between the list view and decision detail view", async () => {
    const user = userEvent.setup();
    const decision = createDecision();

    mocks.getDecisions.mockResolvedValue(
      createPaginatedResponse([decision], { total: 1, page_size: 25 }),
    );
    mocks.getDecisionsDueReview.mockResolvedValue([]);

    renderWithProviders(<DecisionsPage />);

    expect(await screen.findByText("Choose hosting provider")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Open decision-1" }));
    expect(await screen.findByText("Decision Detail: Choose hosting provider")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Back to decisions" }));
    expect(await screen.findByText("Choose hosting provider")).toBeInTheDocument();
  });

  it("renders the empty state and opens the create decision modal", async () => {
    const user = userEvent.setup();

    mocks.getDecisions.mockResolvedValue(createPaginatedResponse([], { total: 0, page_size: 25 }));
    mocks.getDecisionsDueReview.mockResolvedValue([]);

    renderWithProviders(<DecisionsPage />);

    expect(await screen.findByText("No decisions yet")).toBeInTheDocument();

    await user.click(screen.getAllByRole("button", { name: "New Decision" })[0]);
    expect(screen.getByText("Create Decision Modal Open")).toBeInTheDocument();
  });

  it("shows the loading skeletons while decisions are still loading", async () => {
    let resolveDecisions: ((value: ReturnType<typeof createPaginatedResponse>) => void) | null =
      null;

    mocks.getDecisions.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveDecisions = resolve;
        }),
    );
    mocks.getDecisionsDueReview.mockResolvedValue([]);

    renderWithProviders(<DecisionsPage />);

    expect(await screen.findAllByTestId("skeleton")).toHaveLength(5);
    resolveDecisions?.(createPaginatedResponse([], { total: 0, page_size: 25 }));
  });

  it("hides the due-review banner and shows the filtered empty state", async () => {
    const user = userEvent.setup();
    const pendingDecision = createDecision();

    mocks.getDecisions.mockResolvedValue(createPaginatedResponse([], { total: 0, page_size: 25 }));
    mocks.getDecisionsDueReview.mockResolvedValue([pendingDecision]);

    renderWithProviders(<DecisionsPage />);

    expect(await screen.findByText("1 decision due for review")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Pending Review" }));

    expect(await screen.findByText("No pending review decisions")).toBeInTheDocument();
    expect(screen.queryByText("1 decision due for review")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Review Now" })).not.toBeInTheDocument();
  });

  it("renders the page error when decisions fail to load", async () => {
    mocks.getDecisions.mockRejectedValue(new Error("decisions failed"));
    mocks.getDecisionsDueReview.mockResolvedValue([]);

    renderWithProviders(<DecisionsPage />);

    expect(await screen.findByText("Page Error: decisions failed")).toBeInTheDocument();
  });

  it("falls back to the default error message when the rejection has no message", async () => {
    mocks.getDecisions.mockRejectedValue({});
    mocks.getDecisionsDueReview.mockResolvedValue([]);

    renderWithProviders(<DecisionsPage />);

    expect(await screen.findByText("Page Error: Failed to load decisions")).toBeInTheDocument();
  });
});

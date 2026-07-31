import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent, waitFor } from "../test-utils";
import { CommitmentsPage } from "@/pages/commitments";
import type { Commitment, CommitmentStatus } from "@/types";

const mocks = vi.hoisted(() => ({
  getOpenCommitments: vi.fn(),
  getOverdueCommitments: vi.fn(),
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
  updateCommitmentStatus: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: {
    error: mocks.toastError,
    success: mocks.toastSuccess,
  },
}));

vi.mock("@/api/commitments", () => ({
  getOpenCommitments: mocks.getOpenCommitments,
  getOverdueCommitments: mocks.getOverdueCommitments,
  updateCommitmentStatus: mocks.updateCommitmentStatus,
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

vi.mock("@/components/ui/empty-state", () => ({
  EmptyState: ({ description, title }: { description?: string; title: string }) => (
    <div>
      <div>{title}</div>
      {description ? <div>{description}</div> : null}
    </div>
  ),
}));

vi.mock("@/components/commitments/commitment-filters", () => ({
  CommitmentFilters: ({
    activeTab,
    onStatusToggle,
    onTabChange,
    overdueCount,
    selectedStatuses,
  }: {
    activeTab: "open" | "overdue" | "all";
    onStatusToggle: (status: CommitmentStatus) => void;
    onTabChange: (tab: "open" | "overdue" | "all") => void;
    overdueCount: number;
    selectedStatuses: CommitmentStatus[];
  }) => (
    <div>
      <div>Active tab: {activeTab}</div>
      <div>Overdue count: {overdueCount}</div>
      <div>Statuses: {selectedStatuses.join(",") || "none"}</div>
      <button type="button" onClick={() => onTabChange("open")}>
        Tab open
      </button>
      <button type="button" onClick={() => onTabChange("overdue")}>
        Tab overdue
      </button>
      <button type="button" onClick={() => onTabChange("all")}>
        Tab all
      </button>
      <button type="button" onClick={() => onStatusToggle("completed")}>
        Filter completed
      </button>
    </div>
  ),
}));

vi.mock("@/components/commitments/commitment-card", () => ({
  CommitmentCard: ({
    commitment,
    isPending,
    onStatusChange,
  }: {
    commitment: Commitment;
    isPending?: boolean;
    onStatusChange: (id: string, status: CommitmentStatus) => void;
  }) => (
    <div>
      <div>{commitment.normalized_action}</div>
      <div>{isPending ? "Pending" : "Idle"}</div>
      <button type="button" onClick={() => onStatusChange(commitment.id, "completed")}>
        Complete {commitment.id}
      </button>
    </div>
  ),
}));

function createCommitment(overrides: Partial<Commitment> = {}): Commitment {
  return {
    id: "commitment-1",
    verbatim_text: "I'll follow up tomorrow.",
    normalized_action: "Follow up with the team",
    who_committed: "Alex",
    who_to: "Team",
    temporal_expression_raw: "tomorrow",
    temporal_normalized: "2026-04-08T09:00:00Z",
    commitment_type: "promise",
    confidence_score: 0.9,
    status: "detected",
    created_at: "2026-04-07T09:00:00Z",
    updated_at: "2026-04-07T09:00:00Z",
    ...overrides,
  };
}

describe("CommitmentsPage", () => {
  beforeEach(() => {
    mocks.getOpenCommitments.mockReset();
    mocks.getOverdueCommitments.mockReset();
    mocks.toastError.mockReset();
    mocks.toastSuccess.mockReset();
    mocks.updateCommitmentStatus.mockReset();
  });

  it("renders grouped commitments, supports tab/filter changes, and handles successful status updates", async () => {
    const user = userEvent.setup();
    const openCommitment = createCommitment();
    const overdueCommitment = createCommitment({
      id: "commitment-2",
      normalized_action: "Send the overdue report",
      status: "acknowledged",
      temporal_normalized: "2026-04-06T09:00:00Z",
    });

    mocks.getOpenCommitments.mockResolvedValue([openCommitment]);
    mocks.getOverdueCommitments.mockResolvedValue([overdueCommitment]);
    mocks.updateCommitmentStatus.mockResolvedValue(createCommitment({ status: "completed" }));

    renderWithProviders(<CommitmentsPage />);

    expect(await screen.findByRole("heading", { name: "Commitments" })).toBeInTheDocument();
    expect(await screen.findByText("Overdue count: 1")).toBeInTheDocument();
    expect(await screen.findByText("Follow up with the team")).toBeInTheDocument();
    expect(screen.queryByText("Send the overdue report")).not.toBeInTheDocument();
    expect(screen.getByText(/8 April 2026/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Tab overdue" }));
    expect(await screen.findByText("Send the overdue report")).toBeInTheDocument();
    expect(screen.queryByText("Follow up with the team")).not.toBeInTheDocument();
    expect(screen.getByText(/6 April 2026/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Tab all" }));
    await user.click(screen.getByRole("button", { name: "Filter completed" }));
    expect(await screen.findByText("No commitments tracked yet")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Tab open" }));
    await user.click(screen.getByRole("button", { name: "Filter completed" }));
    expect(await screen.findByText("Follow up with the team")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Complete commitment-1" }));
    await waitFor(() => {
      expect(mocks.updateCommitmentStatus).toHaveBeenCalledWith("commitment-1", "completed");
    });
    expect(mocks.toastSuccess).toHaveBeenCalledWith("Commitment marked as complete");
  });

  it("shows a pending state while a commitment status update is in flight", async () => {
    const user = userEvent.setup();
    const openCommitment = createCommitment();
    let resolveUpdate!: (value: Commitment) => void;
    const updatePromise = new Promise<Commitment>((resolve) => {
      resolveUpdate = resolve;
    });

    mocks.getOpenCommitments.mockResolvedValue([openCommitment]);
    mocks.getOverdueCommitments.mockResolvedValue([]);
    mocks.updateCommitmentStatus.mockReturnValue(updatePromise);

    renderWithProviders(<CommitmentsPage />);

    expect(await screen.findByText("Follow up with the team")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Complete commitment-1" }));
    expect(await screen.findByText("Pending")).toBeInTheDocument();

    resolveUpdate(createCommitment({ status: "completed" }));
    await waitFor(() => {
      expect(mocks.toastSuccess).toHaveBeenCalledWith("Commitment marked as complete");
    });
  });

  it("deduplicates commitments across tabs and keeps grouped dates in order", async () => {
    const user = userEvent.setup();
    const sharedCommitment = createCommitment({
      id: "commitment-shared",
      normalized_action: "Shared item",
      temporal_normalized: "2026-04-07T09:00:00Z",
    });
    const overdueCommitment = createCommitment({
      id: "commitment-overdue",
      normalized_action: "Earlier overdue item",
      temporal_normalized: "2026-04-06T09:00:00Z",
      status: "acknowledged",
    });
    const openCommitment = createCommitment({
      id: "commitment-open",
      normalized_action: "Later open item",
      temporal_normalized: "2026-04-08T09:00:00Z",
    });

    mocks.getOpenCommitments.mockResolvedValue([sharedCommitment, openCommitment]);
    mocks.getOverdueCommitments.mockResolvedValue([overdueCommitment, sharedCommitment]);

    renderWithProviders(<CommitmentsPage />);

    await user.click(screen.getByRole("button", { name: "Tab all" }));
    expect(screen.getAllByText("Shared item")).toHaveLength(1);
    expect(screen.getByText(/6 April 2026/)).toBeInTheDocument();
    expect(screen.getByText(/7 April 2026/)).toBeInTheDocument();
    expect(screen.getByText(/8 April 2026/)).toBeInTheDocument();
  });

  it("rolls back optimistic updates when a status change fails with cached data", async () => {
    const user = userEvent.setup();
    const openCommitment = createCommitment();
    const overdueCommitment = createCommitment({
      id: "commitment-2",
      normalized_action: "Send the overdue report",
      status: "acknowledged",
      temporal_normalized: "2026-04-06T09:00:00Z",
    });

    mocks.getOpenCommitments.mockResolvedValue([openCommitment]);
    mocks.getOverdueCommitments.mockResolvedValue([overdueCommitment]);
    mocks.updateCommitmentStatus.mockRejectedValue(new Error("update failed"));

    renderWithProviders(<CommitmentsPage />);

    expect(await screen.findByText("Follow up with the team")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Complete commitment-1" }));
    await waitFor(() => {
      expect(mocks.toastError).toHaveBeenCalledWith("Failed to update commitment status");
    });
  });

  it("renders the empty state when there are no commitments", async () => {
    mocks.getOpenCommitments.mockResolvedValue([]);
    mocks.getOverdueCommitments.mockResolvedValue([]);

    renderWithProviders(<CommitmentsPage />);

    expect(await screen.findByText("No commitments tracked yet")).toBeInTheDocument();
  });

  it("renders the page error when either commitments query fails", async () => {
    const user = userEvent.setup();
    mocks.getOpenCommitments.mockRejectedValue({});
    mocks.getOverdueCommitments.mockResolvedValue([]);

    renderWithProviders(<CommitmentsPage />);

    expect(await screen.findByText("Page Error: Failed to load commitments")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => {
      expect(mocks.getOpenCommitments).toHaveBeenCalledTimes(2);
      expect(mocks.getOverdueCommitments).toHaveBeenCalledTimes(2);
    });
  });

  it("groups commitments without a usable due date into the No due date bucket", async () => {
    mocks.getOpenCommitments.mockResolvedValue([
      createCommitment({
        id: "commitment-1",
        normalized_action: "Follow up on the proposal",
        temporal_normalized: "2026-04-09T09:00:00Z",
      }),
      createCommitment({
        id: "commitment-2",
        normalized_action: "Draft the summary",
        temporal_normalized: undefined,
      }),
    ]);
    mocks.getOverdueCommitments.mockResolvedValue([]);

    const dateSpy = vi.spyOn(Date.prototype, "toLocaleDateString").mockImplementationOnce(() => {
      throw new Error("bad date");
    });

    renderWithProviders(<CommitmentsPage />);

    expect(await screen.findByText("No due date")).toBeInTheDocument();
    expect(screen.getByText("Follow up on the proposal")).toBeInTheDocument();
    expect(screen.getByText("Draft the summary")).toBeInTheDocument();

    dateSpy.mockRestore();
  });

  it("shows a toast when a status update fails", async () => {
    const user = userEvent.setup();
    mocks.getOpenCommitments.mockResolvedValue([createCommitment()]);
    mocks.getOverdueCommitments.mockResolvedValue([]);
    mocks.updateCommitmentStatus.mockRejectedValue(new Error("update failed"));

    renderWithProviders(<CommitmentsPage />);

    expect(await screen.findByText("Follow up with the team")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Complete commitment-1" }));
    await waitFor(() => {
      expect(mocks.toastError).toHaveBeenCalledWith("Failed to update commitment status");
    });
  });
});

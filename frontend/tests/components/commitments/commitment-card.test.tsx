import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent } from "../../test-utils";
import { CommitmentCard } from "@/components/commitments/commitment-card";
import type { Commitment } from "@/types";

vi.mock("@/lib/utils", async () => {
  const actual = await vi.importActual<typeof import("@/lib/utils")>("@/lib/utils");

  return {
    ...actual,
    formatRelativeTime: () => "2d ago",
  };
});

function createCommitment(overrides: Partial<Commitment> = {}): Commitment {
  return {
    id: "commitment-1",
    verbatim_text: "I'll send the summary tomorrow.",
    normalized_action: "Send the weekly summary",
    who_committed: "Alex",
    who_to: "Team",
    temporal_expression_raw: "tomorrow",
    temporal_normalized: "2000-01-01T09:00:00Z",
    commitment_type: "promise",
    confidence_score: 0.86,
    status: "detected",
    created_at: "2026-04-07T09:00:00Z",
    updated_at: "2026-04-07T09:00:00Z",
    ...overrides,
  };
}

describe("CommitmentCard", () => {
  it("renders overdue detected commitments and forwards action callbacks", async () => {
    const user = userEvent.setup();
    const onStatusChange = vi.fn();
    const { container } = renderWithProviders(
      <CommitmentCard commitment={createCommitment()} onStatusChange={onStatusChange} />,
    );

    expect(screen.getByText("Detected")).toBeInTheDocument();
    expect(screen.getByText("promise")).toBeInTheDocument();
    expect(screen.getByText("Overdue")).toBeInTheDocument();
    expect(screen.getByText("Send the weekly summary")).toBeInTheDocument();
    expect(screen.getByText("Alex")).toBeInTheDocument();
    expect(screen.getByText("Team")).toBeInTheDocument();
    expect(screen.getByText("86%")).toBeInTheDocument();

    const progressBar = container.querySelector(
      ".absolute.inset-y-0.left-0.rounded-full.transition-all",
    ) as HTMLElement | null;
    expect(progressBar?.style.width).toBe("86%");

    await user.click(screen.getByRole("button", { name: "Acknowledge" }));
    await user.click(screen.getByRole("button", { name: "Complete" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onStatusChange).toHaveBeenNthCalledWith(1, "commitment-1", "acknowledged");
    expect(onStatusChange).toHaveBeenNthCalledWith(2, "commitment-1", "completed");
    expect(onStatusChange).toHaveBeenNthCalledWith(3, "commitment-1", "cancelled");
  });

  it("renders acknowledged commitments without the acknowledge button", () => {
    renderWithProviders(
      <CommitmentCard
        commitment={createCommitment({
          status: "acknowledged",
          commitment_type: "reminder",
        })}
        onStatusChange={vi.fn()}
      />,
    );

    expect(screen.getByText("Acknowledged")).toBeInTheDocument();
    expect(screen.getByText("reminder")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Acknowledge" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Complete" })).toBeInTheDocument();
  });

  it("renders completed commitments without action buttons and falls back to the raw temporal expression", () => {
    renderWithProviders(
      <CommitmentCard
        commitment={createCommitment({
          confidence_score: 0.35,
          status: "completed",
          temporal_normalized: null,
        })}
        onStatusChange={vi.fn()}
      />,
    );

    expect(screen.getByText("Completed")).toBeInTheDocument();
    expect(screen.getByText("tomorrow")).toBeInTheDocument();
    expect(screen.getByText("35%")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Complete" })).not.toBeInTheDocument();
  });
});

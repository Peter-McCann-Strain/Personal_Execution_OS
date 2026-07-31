import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders, screen, waitFor } from "../../test-utils";
import { CreateDecisionModal } from "@/components/decisions/create-decision-modal";

const mocks = vi.hoisted(() => ({
  createDecision: vi.fn(),
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
  createDecision: mocks.createDecision,
}));

describe("CreateDecisionModal", () => {
  beforeEach(() => {
    mocks.createDecision.mockReset();
    mocks.toastError.mockReset();
    mocks.toastSuccess.mockReset();
  });

  it("collects decision data, submits it, and closes on success", async () => {
    const onOpenChange = vi.fn();

    mocks.createDecision.mockResolvedValue({
      id: "decision-2",
      title: "Choose hosting provider",
    });

    renderWithProviders(<CreateDecisionModal open onOpenChange={onOpenChange} />);

    const dialog = screen.getByRole("dialog", { name: "New Decision" });
    expect(dialog).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create Decision" })).toBeDisabled();

    fireEvent.change(screen.getByPlaceholderText("What decision are you making?"), {
      target: { value: "Choose hosting provider" },
    });
    fireEvent.change(screen.getByPlaceholderText("What did you decide?"), {
      target: { value: "Use provider A" },
    });
    fireEvent.change(screen.getByPlaceholderText("What circumstances led to this decision?"), {
      target: { value: "We needed lower latency" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Add option" }));
    fireEvent.change(screen.getAllByPlaceholderText("Describe an option...")[0], {
      target: { value: "Option A" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add option" }));
    fireEvent.change(screen.getAllByPlaceholderText("Describe an option...")[1], {
      target: { value: "Option B" },
    });

    fireEvent.change(screen.getByPlaceholderText("Why did you make this choice?"), {
      target: { value: "Latency and support" },
    });
    fireEvent.change(screen.getByPlaceholderText("What do you expect will happen?"), {
      target: { value: "Simpler operations" },
    });
    fireEvent.change(screen.getByPlaceholderText("Add a tag..."), {
      target: { value: "infra" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    const reviewDateInput = document.querySelector('input[type="date"]') as HTMLInputElement | null;
    expect(reviewDateInput).not.toBeNull();
    if (!reviewDateInput) {
      return;
    }
    fireEvent.change(reviewDateInput, { target: { value: "2026-04-15" } });

    fireEvent.click(screen.getByRole("button", { name: "Create Decision" }));

    await waitFor(() => {
      expect(mocks.createDecision).toHaveBeenCalledWith({
        title: "Choose hosting provider",
        decision_made: "Use provider A",
        context: "We needed lower latency",
        options_considered: ["Option A", "Option B"],
        reasoning: "Latency and support",
        expected_outcome: "Simpler operations",
        tags: ["infra"],
        review_date: "2026-04-15",
      });
    });
    expect(mocks.toastSuccess).toHaveBeenCalledWith("Decision recorded");
    expect(onOpenChange).toHaveBeenCalledWith(false);
  }, 15000);

  it("submits only the required fields when optional inputs are left blank", async () => {
    const onOpenChange = vi.fn();

    mocks.createDecision.mockResolvedValue({
      id: "decision-3",
      title: "Choose observability stack",
    });

    renderWithProviders(<CreateDecisionModal open onOpenChange={onOpenChange} />);

    fireEvent.change(screen.getByPlaceholderText("What decision are you making?"), {
      target: { value: "Choose observability stack" },
    });
    fireEvent.change(screen.getByPlaceholderText("What did you decide?"), {
      target: { value: "Use OpenTelemetry" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Create Decision" }));

    await waitFor(() => {
      expect(mocks.createDecision).toHaveBeenCalledWith({
        title: "Choose observability stack",
        decision_made: "Use OpenTelemetry",
      });
    });
    expect(mocks.toastSuccess).toHaveBeenCalledWith("Decision recorded");
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("shows an error toast when creating a decision fails", async () => {
    mocks.createDecision.mockRejectedValueOnce(new Error("decision failed"));

    renderWithProviders(<CreateDecisionModal open onOpenChange={vi.fn()} />);

    fireEvent.change(screen.getByPlaceholderText("What decision are you making?"), {
      target: { value: "Choose hosting provider" },
    });
    fireEvent.change(screen.getByPlaceholderText("What did you decide?"), {
      target: { value: "Use provider A" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Create Decision" }));

    await waitFor(() => {
      expect(mocks.toastError).toHaveBeenCalledWith("Failed to create decision");
    });
    expect(screen.getByRole("dialog", { name: "New Decision" })).toBeInTheDocument();
  });

  it("clears the dialog when cancelled", async () => {
    const onOpenChange = vi.fn();

    renderWithProviders(<CreateDecisionModal open onOpenChange={onOpenChange} />);

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("prevents duplicate tags and allows removing dynamic options", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();

    mocks.createDecision.mockResolvedValue({
      id: "decision-4",
      title: "Choose incident process",
    });

    renderWithProviders(<CreateDecisionModal open onOpenChange={onOpenChange} />);

    await user.type(
      screen.getByPlaceholderText("What decision are you making?"),
      "Choose incident process",
    );
    await user.type(
      screen.getByPlaceholderText("What did you decide?"),
      "Use a written incident playbook",
    );

    await user.click(screen.getByRole("button", { name: "Add option" }));
    await user.click(screen.getByRole("button", { name: "Add option" }));
    const optionInputs = screen.getAllByPlaceholderText("Describe an option...");
    await user.type(optionInputs[0], "Document in the runbook");
    await user.type(optionInputs[1], "Keep as-is");
    await user.click(screen.getByRole("button", { name: "Remove option 2" }));

    const tagInput = screen.getByPlaceholderText("Add a tag...");
    await user.type(tagInput, "incident");
    await user.keyboard("{Enter}");
    await user.type(tagInput, "incident");
    await user.click(screen.getByRole("button", { name: "Add" }));

    expect(screen.getAllByText("incident")).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "Remove incident" }));
    expect(screen.queryByText("incident")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Create Decision" }));

    await waitFor(() => {
      expect(mocks.createDecision).toHaveBeenCalledWith({
        title: "Choose incident process",
        decision_made: "Use a written incident playbook",
        options_considered: ["Document in the runbook"],
      });
    });
    expect(mocks.toastSuccess).toHaveBeenCalledWith("Decision recorded");
    expect(onOpenChange).toHaveBeenCalledWith(false);
  }, 15000);
});

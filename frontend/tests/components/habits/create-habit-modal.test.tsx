import { describe, expect, it, vi } from "vitest";
import { fireEvent } from "@testing-library/react";
import { renderWithProviders, screen, userEvent, waitFor } from "../../test-utils";
import { CreateHabitModal } from "@/components/habits/create-habit-modal";

describe("CreateHabitModal", () => {
  it("does not render when closed", () => {
    const { container } = renderWithProviders(
      <CreateHabitModal open={false} onClose={vi.fn()} onCreate={vi.fn()} />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("normalizes form input and submits habit data", async () => {
    const onClose = vi.fn();
    const onCreate = vi.fn();

    renderWithProviders(<CreateHabitModal open onClose={onClose} onCreate={onCreate} />);

    fireEvent.change(screen.getByPlaceholderText("e.g. Morning meditation"), {
      target: { value: "  Deep work  " },
    });
    fireEvent.change(screen.getByPlaceholderText("Optional description..."), {
      target: { value: " Focus block " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Custom" }));
    fireEvent.change(screen.getByPlaceholderText("N"), {
      target: { value: "3" },
    });

    const tagInput = screen.getByPlaceholderText("Add tags...");
    fireEvent.change(tagInput, { target: { value: " Focus " } });
    fireEvent.keyDown(tagInput, { key: "Enter", code: "Enter" });
    fireEvent.change(tagInput, { target: { value: "Focus" } });
    fireEvent.keyDown(tagInput, { key: "Enter", code: "Enter" });

    expect(screen.getByText("focus")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Create Habit" }));

    await waitFor(() => {
      expect(onCreate).toHaveBeenCalledWith({
        name: "Deep work",
        description: "Focus block",
        frequency: "custom",
        frequency_days: 3,
        tags: ["focus"],
      });
    });

    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("handles tag editing, reset-on-close, and disabled submitting", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const onCreate = vi.fn();

    const { rerender } = renderWithProviders(
      <CreateHabitModal open onClose={onClose} onCreate={onCreate} isCreating />,
    );

    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Create Habit" })).toBeDisabled();

    rerender(<CreateHabitModal open onClose={onClose} onCreate={onCreate} />);

    fireEvent.change(screen.getByPlaceholderText("e.g. Morning meditation"), {
      target: { value: "Reading" },
    });
    fireEvent.change(screen.getByPlaceholderText("Optional description..."), {
      target: { value: "Read before bed" },
    });

    const tagInput = screen.getByPlaceholderText("Add tags...");
    fireEvent.change(tagInput, { target: { value: "focus" } });
    fireEvent.keyDown(tagInput, { key: "Enter", code: "Enter" });
    fireEvent.change(tagInput, { target: { value: "deep work" } });
    fireEvent.blur(tagInput);

    expect(screen.getByText("focus")).toBeInTheDocument();
    expect(screen.getByText("deep work")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Remove tag focus" }));
    expect(screen.queryByText("focus")).not.toBeInTheDocument();

    fireEvent.change(tagInput, { target: { value: "" } });
    fireEvent.keyDown(tagInput, { key: "Backspace", code: "Backspace" });
    expect(screen.queryByText("deep work")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Create Habit" }));
    expect(onCreate).toHaveBeenCalledWith({
      name: "Reading",
      description: "Read before bed",
    });

    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.getByPlaceholderText("e.g. Morning meditation")).toHaveValue("");
    expect(screen.getByPlaceholderText("Optional description...")).toHaveValue("");
  });

  it("supports weekly and monthly frequencies and closes from the backdrop", async () => {
    const onClose = vi.fn();
    const onCreate = vi.fn();

    const { rerender } = renderWithProviders(
      <CreateHabitModal open onClose={onClose} onCreate={onCreate} />,
    );

    fireEvent.change(screen.getByPlaceholderText("e.g. Morning meditation"), {
      target: { value: "Weekly planning" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Weekly" }));
    fireEvent.click(screen.getByRole("button", { name: "Create Habit" }));

    await waitFor(() => {
      expect(onCreate).toHaveBeenCalledWith({
        name: "Weekly planning",
        frequency: "weekly",
      });
    });

    rerender(<CreateHabitModal open onClose={onClose} onCreate={onCreate} />);

    fireEvent.change(screen.getByPlaceholderText("e.g. Morning meditation"), {
      target: { value: "Monthly review" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Monthly" }));
    fireEvent.click(screen.getByRole("button", { name: "Create Habit" }));

    await waitFor(() => {
      expect(onCreate).toHaveBeenCalledWith({
        name: "Monthly review",
        frequency: "monthly",
      });
    });

    fireEvent.click(document.querySelector(".backdrop-blur-sm") as Element);
    expect(onClose).toHaveBeenCalled();
  });

  it("allows custom frequency without days and ignores blank submissions or blank tags", async () => {
    const onCreate = vi.fn();

    renderWithProviders(<CreateHabitModal open onClose={vi.fn()} onCreate={onCreate} />);

    fireEvent.click(screen.getByRole("button", { name: "Create Habit" }));
    expect(onCreate).not.toHaveBeenCalled();

    fireEvent.change(screen.getByPlaceholderText("e.g. Morning meditation"), {
      target: { value: "Custom ritual" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Custom" }));

    const tagInput = screen.getByPlaceholderText("Add tags...");
    fireEvent.change(tagInput, { target: { value: "   " } });
    fireEvent.blur(tagInput);
    expect(screen.queryByRole("button", { name: /^Remove tag / })).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("Add tags...")).toBeInTheDocument();

    fireEvent.change(tagInput, { target: { value: "focus" } });
    fireEvent.keyDown(tagInput, { key: "Enter", code: "Enter" });
    fireEvent.change(tagInput, { target: { value: "keep" } });
    fireEvent.keyDown(tagInput, { key: "Backspace", code: "Backspace" });
    expect(screen.getByText("focus")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Create Habit" }));

    await waitFor(() => {
      expect(onCreate).toHaveBeenCalledWith({
        name: "Custom ritual",
        frequency: "custom",
        tags: ["focus"],
      });
    });
  });
});

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent } from "@testing-library/react";
import { act, renderWithProviders, screen } from "../../test-utils";
import { GoalCard } from "@/components/goals/goal-card";
import { createGoal } from "../../factories";

describe("GoalCard", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-04-08T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders goal metadata, debounces progress updates, and forwards child selection", async () => {
    const onProgressChange = vi.fn();
    const onChildSelect = vi.fn();

    renderWithProviders(
      <GoalCard
        goal={createGoal({
          title: "Runtime hardening",
          priority: 8,
          progress: 65,
          deadline: "2026-04-11T12:00:00Z",
          evidence: ["Added streaming contracts"],
        })}
        childGoals={[
          createGoal({
            id: "goal-2",
            title: "Child milestone",
            progress: 80,
            parent_id: "goal-1",
          }),
        ]}
        onProgressChange={onProgressChange}
        onChildSelect={onChildSelect}
      />,
    );
    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.getByRole("heading", { name: "Runtime hardening" })).toBeInTheDocument();
    expect(screen.getByText("Added streaming contracts")).toBeInTheDocument();
    expect(screen.getByText(/\(3d left\)/)).toBeInTheDocument();

    act(() => {
      screen.getByRole("button", { name: "Increase progress" }).click();
      vi.advanceTimersByTime(401);
    });
    expect(onProgressChange).toHaveBeenCalledWith("goal-1", 0.7);

    fireEvent.click(screen.getByRole("button", { name: /Child milestone/i }));
    expect(onChildSelect).toHaveBeenCalledWith(expect.objectContaining({ id: "goal-2" }));
  });

  it("forwards status changes and renders overdue copy", async () => {
    const onStatusChange = vi.fn();

    renderWithProviders(
      <GoalCard
        goal={createGoal({
          status: "paused",
          deadline: "2026-04-06T12:00:00Z",
        })}
        onStatusChange={onStatusChange}
      />,
    );
    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.getByText(/\(2d overdue\)/)).toBeInTheDocument();
    screen.getByRole("button", { name: "completed" }).click();
    expect(onStatusChange).toHaveBeenCalledWith("goal-1", "completed");
  });

  it("renders fallback copy and syncs local progress after prop changes", async () => {
    const { rerender } = renderWithProviders(
      <GoalCard
        goal={createGoal({
          deadline: null,
          evidence: [],
          progress: 10,
        })}
      />,
    );
    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.getByText("No deadline set")).toBeInTheDocument();
    expect(screen.queryByText(/Evidence \(/)).not.toBeInTheDocument();
    expect(screen.getByText("10%")).toBeInTheDocument();

    rerender(
      <GoalCard
        goal={createGoal({
          id: "goal-2",
          deadline: null,
          evidence: [],
          progress: 80,
        })}
      />,
    );

    await act(async () => {
      vi.runAllTicks();
    });
    expect(screen.getByText("80%")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Decrease progress" }));
    expect(screen.getByText("75%")).toBeInTheDocument();
  });

  it("clamps progress controls at the bounds and exposes every status option", async () => {
    const onProgressChange = vi.fn();
    const onStatusChange = vi.fn();

    renderWithProviders(
      <GoalCard
        goal={createGoal({
          progress: 100,
          status: "active",
        })}
        onProgressChange={onProgressChange}
        onStatusChange={onStatusChange}
      />,
    );
    await act(async () => {
      await Promise.resolve();
    });

    act(() => {
      fireEvent.click(screen.getByRole("button", { name: "Increase progress" }));
      vi.advanceTimersByTime(401);
    });
    expect(onProgressChange).toHaveBeenLastCalledWith("goal-1", 1);

    act(() => {
      fireEvent.click(screen.getByRole("button", { name: "Decrease progress" }));
      vi.advanceTimersByTime(401);
    });
    expect(onProgressChange).toHaveBeenLastCalledWith("goal-1", 0.95);

    fireEvent.click(screen.getByRole("button", { name: "paused" }));
    fireEvent.click(screen.getByRole("button", { name: "completed" }));
    fireEvent.click(screen.getByRole("button", { name: "cancelled" }));

    expect(onStatusChange).toHaveBeenNthCalledWith(1, "goal-1", "paused");
    expect(onStatusChange).toHaveBeenNthCalledWith(2, "goal-1", "completed");
    expect(onStatusChange).toHaveBeenNthCalledWith(3, "goal-1", "cancelled");
  });
});

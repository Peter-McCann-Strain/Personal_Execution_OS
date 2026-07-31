import { describe, expect, it, vi } from "vitest";
import { fireEvent } from "@testing-library/react";
import { renderWithProviders, screen, userEvent, waitFor } from "../../test-utils";
import { GoalTree } from "@/components/goals/goal-tree";
import { createGoal } from "../../factories";

describe("GoalTree", () => {
  it("renders an empty state when there are no goals", () => {
    renderWithProviders(<GoalTree goals={[]} />);

    expect(screen.getByText("No goals defined yet")).toBeInTheDocument();
  });

  it("groups goals, supports collapse/expand, and forwards selection", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const parent = createGoal({
      id: "goal-1",
      title: "Parent goal",
      goal_type: "quarterly",
      priority: 2,
      evidence: ["metric"],
    });
    const child = createGoal({
      id: "goal-2",
      title: "Child goal",
      parent_id: "goal-1",
      goal_type: "weekly",
      priority: 4,
    });
    const ungrouped = createGoal({
      id: "goal-3",
      title: "Other goal",
      goal_type: null,
      priority: 1,
    });

    renderWithProviders(<GoalTree goals={[parent, child, ungrouped]} onSelect={onSelect} />);

    expect(screen.getByText("quarterly Goals")).toBeInTheDocument();
    expect(screen.getByText("Uncategorized")).toBeInTheDocument();
    expect(screen.getByText("Parent goal")).toBeInTheDocument();
    expect(screen.getByText("Child goal")).toBeInTheDocument();
    expect(screen.getByText("Other goal")).toBeInTheDocument();

    const parentRow = screen.getByText("Parent goal").closest(".group");
    expect(parentRow).not.toBeNull();
    if (!parentRow) {
      return;
    }

    await user.click(parentRow);
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: "goal-1" }));
    await waitFor(() => {
      expect(screen.queryByText("Child goal")).not.toBeInTheDocument();
    });

    await user.click(parentRow);
    expect(await screen.findByText("Child goal")).toBeInTheDocument();
  });

  it("orders groups and nested goals by type and priority", async () => {
    const goals = [
      createGoal({
        id: "goal-life-low",
        title: "Life low",
        goal_type: "life",
        priority: 9,
      }),
      createGoal({
        id: "goal-weekly",
        title: "Weekly goal",
        goal_type: "weekly",
        priority: 2,
      }),
      createGoal({
        id: "goal-life-high",
        title: "Life high",
        goal_type: "life",
        priority: 1,
      }),
      createGoal({
        id: "goal-yearly",
        title: "Yearly goal",
        goal_type: "yearly",
        priority: 5,
      }),
      createGoal({
        id: "goal-root",
        title: "Root goal",
        goal_type: null,
        priority: 3,
      }),
      createGoal({
        id: "goal-child-b",
        title: "Child B",
        parent_id: "goal-root",
        priority: 7,
      }),
      createGoal({
        id: "goal-child-a",
        title: "Child A",
        parent_id: "goal-root",
        priority: 1,
      }),
    ];

    renderWithProviders(<GoalTree goals={goals} />);

    const headings = screen.getAllByRole("heading", { level: 3 });
    expect(headings[0]).toHaveTextContent("life Goals");
    expect(headings[1]).toHaveTextContent("yearly Goals");
    expect(headings[2]).toHaveTextContent("weekly Goals");
    expect(headings[3]).toHaveTextContent("Uncategorized");

    expect(screen.getAllByText("Life high")[0]).toBeInTheDocument();
    expect(screen.getAllByText("Life low")[0]).toBeInTheDocument();
    expect(screen.getByText("Yearly goal")).toBeInTheDocument();
    expect(screen.getByText("Root goal")).toBeInTheDocument();
    expect(screen.getByText("Child A")).toBeInTheDocument();
    expect(screen.getByText("Child B")).toBeInTheDocument();

    const rootRow = screen.getByText("Root goal").closest(".group");
    expect(rootRow).not.toBeNull();
    if (!rootRow) return;

    fireEvent.click(rootRow);
    await waitFor(() => {
      expect(screen.queryByText("Child A")).not.toBeInTheDocument();
    });
  });

  it("falls back to the raw status label for unknown statuses", () => {
    const legacyGoal = createGoal({
      id: "goal-legacy",
      title: "Legacy goal",
      status: "archived" as never,
      priority: 4,
    });

    renderWithProviders(<GoalTree goals={[legacyGoal]} />);

    expect(screen.getByText("Legacy goal")).toBeInTheDocument();
    expect(screen.getByText("archived")).toBeInTheDocument();
  });
});

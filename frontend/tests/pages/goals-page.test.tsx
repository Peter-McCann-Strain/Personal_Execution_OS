import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent, waitFor } from "../test-utils";
import { GoalsPage } from "@/pages/goals";
import { createGoal, createPaginatedResponse } from "../factories";
import type { Goal } from "@/types";

const mocks = vi.hoisted(() => ({
  createGoal: vi.fn(),
  getGoals: vi.fn(),
  updateGoalProgress: vi.fn(),
}));

vi.mock("@/api/goals", () => ({
  createGoal: mocks.createGoal,
  getGoals: mocks.getGoals,
  updateGoalProgress: mocks.updateGoalProgress,
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

vi.mock("@/components/goals/goal-tree", () => ({
  GoalTree: ({ goals, onSelect }: { goals: Goal[]; onSelect?: (goal: Goal) => void }) => (
    <div>
      {goals.map((goal) => (
        <button key={goal.id} type="button" onClick={() => onSelect?.(goal)}>
          Open {goal.title}
        </button>
      ))}
    </div>
  ),
}));

vi.mock("@/components/goals/goal-card", () => ({
  GoalCard: ({
    goal,
    childGoals,
    onProgressChange,
    onChildSelect,
  }: {
    goal: Goal;
    childGoals?: Goal[];
    onProgressChange?: (id: string, progress: number) => void;
    onChildSelect?: (goal: Goal) => void;
  }) => (
    <div>
      <div>Goal detail {goal.title}</div>
      <div>Children {childGoals?.length ?? 0}</div>
      <button type="button" onClick={() => onProgressChange?.(goal.id, 90)}>
        Push progress
      </button>
      {childGoals?.[0] ? (
        <button type="button" onClick={() => onChildSelect?.(childGoals[0])}>
          Open child
        </button>
      ) : null}
    </div>
  ),
}));

describe("GoalsPage", () => {
  beforeEach(() => {
    mocks.createGoal.mockReset();
    mocks.getGoals.mockReset();
    mocks.updateGoalProgress.mockReset();
    mocks.createGoal.mockResolvedValue(createGoal());
  });

  it("renders goals, filters them, selects details, and updates progress", async () => {
    const user = userEvent.setup();
    const parent = createGoal({
      id: "goal-1",
      title: "Parent goal",
      status: "active",
      goal_type: "quarterly",
    });
    const child = createGoal({
      id: "goal-2",
      title: "Child goal",
      parent_id: "goal-1",
      goal_type: "weekly",
    });
    const paused = createGoal({
      id: "goal-3",
      title: "Paused goal",
      status: "paused",
      goal_type: "life",
    });

    mocks.getGoals.mockImplementation((params: Record<string, unknown>) => {
      if (params.status === "paused") {
        return Promise.resolve(createPaginatedResponse([paused]));
      }
      if (params.goal_type === "life") {
        return Promise.resolve(createPaginatedResponse([paused]));
      }
      return Promise.resolve(createPaginatedResponse([parent, child]));
    });
    mocks.updateGoalProgress.mockResolvedValue(createGoal({ progress: 90 }));

    renderWithProviders(<GoalsPage />);

    expect(await screen.findByRole("heading", { name: "Goals" })).toBeInTheDocument();
    expect(await screen.findByText("Goal detail Parent goal")).toBeInTheDocument();
    expect(screen.getByText("Children 1")).toBeInTheDocument();

    const selects = screen.getAllByRole("combobox");
    await user.selectOptions(selects[0], "paused");
    await waitFor(() => {
      expect(mocks.getGoals).toHaveBeenLastCalledWith({
        limit: 100,
        status: "paused",
      });
    });

    await user.selectOptions(selects[1], "life");
    await waitFor(() => {
      expect(mocks.getGoals).toHaveBeenLastCalledWith({
        limit: 100,
        status: "paused",
        goal_type: "life",
      });
    });

    await user.selectOptions(selects[0], "all");
    await user.selectOptions(selects[1], "all");

    await user.click(screen.getByRole("button", { name: "Open Child goal" }));
    expect(await screen.findByText("Goal detail Child goal")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Push progress" }));
    await waitFor(() => {
      expect(mocks.updateGoalProgress).toHaveBeenCalledWith("goal-2", 90);
    });
  });

  it("renders the empty state when no goals exist", async () => {
    mocks.getGoals.mockResolvedValue(createPaginatedResponse([]));

    renderWithProviders(<GoalsPage />);

    expect(await screen.findByText("No goals yet")).toBeInTheDocument();
  });

  it("renders the page error when loading fails", async () => {
    mocks.getGoals.mockRejectedValue(new Error("goals failed"));

    renderWithProviders(<GoalsPage />);

    expect(await screen.findByText("Page Error: goals failed")).toBeInTheDocument();
  });
});

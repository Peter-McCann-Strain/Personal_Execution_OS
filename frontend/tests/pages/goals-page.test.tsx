import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent, waitFor } from "../test-utils";
import { GoalsPage } from "@/pages/goals";
import { createGoal, createPaginatedResponse } from "../factories";
import type { Goal } from "@/types";

const mocks = vi.hoisted(() => ({
  createGoal: vi.fn(),
  getGoals: vi.fn(),
  updateGoalProgress: vi.fn(),
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: {
    error: mocks.toastError,
    success: mocks.toastSuccess,
  },
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
  PageError: ({ message, onRetry }: { message: string; onRetry?: () => void }) => (
    <div>
      <div>Page Error: {message}</div>
      <button type="button" onClick={onRetry}>
        Retry goals
      </button>
    </div>
  ),
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
    mocks.toastError.mockReset();
    mocks.toastSuccess.mockReset();
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
    mocks.getGoals
      .mockRejectedValueOnce(new Error("goals failed"))
      .mockResolvedValueOnce(createPaginatedResponse([]));

    renderWithProviders(<GoalsPage />);

    expect(await screen.findByText("Page Error: goals failed")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Retry goals" }));

    expect(await screen.findByText("No goals yet")).toBeInTheDocument();
    expect(mocks.getGoals).toHaveBeenCalledTimes(2);
  });

  it("shows loading placeholders while the goal request is pending", () => {
    mocks.getGoals.mockReturnValue(new Promise(() => undefined));

    const { container } = renderWithProviders(<GoalsPage />);

    expect(container.querySelectorAll(".animate-pulse")).toHaveLength(8);
  });

  it("creates a normalized goal and opens its detail", async () => {
    const user = userEvent.setup();
    const created = createGoal({
      id: "created-goal",
      title: "Launch deliberately",
      goal_type: "monthly",
      priority: 10,
      deadline: "2026-09-15T00:00:00",
    });
    mocks.getGoals
      .mockResolvedValueOnce(createPaginatedResponse([]))
      .mockResolvedValue(createPaginatedResponse([created]));
    mocks.createGoal.mockResolvedValue(created);

    renderWithProviders(<GoalsPage />);

    await screen.findByText("No goals yet");
    await user.click(screen.getAllByRole("button", { name: "New Goal" })[1]);
    await user.type(
      screen.getByPlaceholderText("e.g. Build a calm daily planning habit"),
      "  Launch deliberately  ",
    );
    await user.selectOptions(screen.getByRole("combobox", { name: "" }), "monthly");
    await user.clear(screen.getByRole("spinbutton"));
    await user.type(screen.getByRole("spinbutton"), "10");
    const deadline = document.querySelector<HTMLInputElement>('input[type="date"]');
    expect(deadline).not.toBeNull();
    await user.type(deadline!, "2026-09-15");
    await user.click(screen.getByRole("button", { name: "Create Goal" }));

    await waitFor(() => {
      expect(mocks.createGoal.mock.calls[0]?.[0]).toEqual({
        title: "Launch deliberately",
        goal_type: "monthly",
        priority: 10,
        deadline: "2026-09-15T00:00:00",
      });
    });
    expect(await screen.findByText("Goal detail Launch deliberately")).toBeInTheDocument();
    expect(mocks.toastSuccess).toHaveBeenCalledWith("Goal created");
    expect(screen.queryByRole("heading", { name: "New Goal" })).not.toBeInTheDocument();
  });

  it("resets the create form when cancelled and reports creation errors", async () => {
    const user = userEvent.setup();
    mocks.getGoals.mockResolvedValue(createPaginatedResponse([]));
    mocks.createGoal.mockRejectedValue(new Error("Title already exists"));

    renderWithProviders(<GoalsPage />);

    await screen.findByText("No goals yet");
    await user.click(screen.getAllByRole("button", { name: "New Goal" })[0]);
    const titleInput = screen.getByPlaceholderText("e.g. Build a calm daily planning habit");
    await user.type(titleInput, "Discard me");
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    await user.click(screen.getAllByRole("button", { name: "New Goal" })[0]);
    expect(screen.getByPlaceholderText("e.g. Build a calm daily planning habit")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Create Goal" })).toBeDisabled();

    await user.type(
      screen.getByPlaceholderText("e.g. Build a calm daily planning habit"),
      "Duplicate",
    );
    await user.click(screen.getByRole("button", { name: "Create Goal" }));

    await waitFor(() => {
      expect(mocks.toastError).toHaveBeenCalledWith("Title already exists");
    });
    expect(screen.getByRole("heading", { name: "New Goal" })).toBeInTheDocument();
  });
});

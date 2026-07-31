import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent } from "../../test-utils";
import { GoalProgress, GoalProgressSkeleton } from "@/components/dashboard/goal-progress";
import type { Goal } from "@/types";

const mocks = vi.hoisted(() => ({
  getActiveGoals: vi.fn(),
  navigate: vi.fn(),
}));

vi.mock("@/api/dashboard", () => ({
  getActiveGoals: mocks.getActiveGoals,
}));

vi.mock("react-router", async () => {
  const actual = await vi.importActual<typeof import("react-router")>("react-router");
  return {
    ...actual,
    useNavigate: () => mocks.navigate,
  };
});

function createGoal(overrides: Partial<Goal> = {}): Goal {
  return {
    id: "goal-1",
    title: "Ship the world-class production milestone",
    goal_type: "project",
    parent_id: null,
    priority: 1,
    status: "active",
    progress: 88,
    deadline: null,
    evidence: [],
    created_at: "2026-04-07T09:00:00Z",
    updated_at: "2026-04-07T09:00:00Z",
    ...overrides,
  };
}

describe("GoalProgress", () => {
  beforeEach(() => {
    mocks.getActiveGoals.mockReset();
    mocks.navigate.mockReset();
  });

  it("renders goals and routes item clicks to the goals page", async () => {
    const user = userEvent.setup();
    mocks.getActiveGoals.mockResolvedValue([
      createGoal(),
      createGoal({
        id: "goal-2",
        title: "Keep notes organised",
        progress: 12,
      }),
    ]);

    renderWithProviders(<GoalProgress />);

    expect(await screen.findByText("Goal Progress")).toBeInTheDocument();
    const primaryGoal = await screen.findByRole("button", {
      name: /Ship the world-class/,
    });
    expect(screen.getByText("88%")).toBeInTheDocument();
    expect(screen.getByText("12%")).toBeInTheDocument();

    await user.click(primaryGoal);
    expect(mocks.navigate).toHaveBeenCalledWith("/goals");
  });

  it("renders empty and error states", async () => {
    mocks.getActiveGoals.mockResolvedValueOnce([]);
    const firstRender = renderWithProviders(<GoalProgress />);

    expect(
      await screen.findByText("No active goals. Set your first goal to track progress."),
    ).toBeInTheDocument();
    firstRender.unmount();

    mocks.getActiveGoals.mockRejectedValueOnce(new Error("goals failed"));
    renderWithProviders(<GoalProgress />);

    expect(await screen.findByText("Unable to load goals.")).toBeInTheDocument();
  });

  it("renders the loading skeleton", () => {
    const { container } = renderWithProviders(<GoalProgressSkeleton />);

    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });
});

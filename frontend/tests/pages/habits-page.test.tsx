import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent, waitFor } from "../test-utils";
import { HabitsPage } from "@/pages/habits";
import { createHabit } from "../factories";
import type { Habit, CreateHabitData } from "@/api/habits";

const mocks = vi.hoisted(() => ({
  getHabits: vi.fn(),
  createHabit: vi.fn(),
  completeHabit: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@/api/habits", () => ({
  getHabits: mocks.getHabits,
  createHabit: mocks.createHabit,
  completeHabit: mocks.completeHabit,
}));

vi.mock("sonner", () => ({
  toast: {
    success: mocks.toastSuccess,
    error: mocks.toastError,
  },
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
  PageError: ({ message, onRetry }: { message: string; onRetry: () => void }) => (
    <div>
      <div>Page Error: {message}</div>
      <button type="button" onClick={onRetry}>
        Retry
      </button>
    </div>
  ),
}));

vi.mock("@/components/ui/empty-state", () => ({
  EmptyState: ({
    title,
    description,
    action,
  }: {
    title: string;
    description?: string;
    action?: { label: string; onClick: () => void };
  }) => (
    <div>
      <div>{title}</div>
      {description ? <div>{description}</div> : null}
      {action ? (
        <button type="button" onClick={action.onClick}>
          {action.label}
        </button>
      ) : null}
    </div>
  ),
}));

vi.mock("@/components/habits/habit-card", () => ({
  HabitCard: ({
    habit,
    onComplete,
    onSelect,
    isCompleting,
  }: {
    habit: Habit;
    onComplete: (id: string) => void;
    onSelect: (habit: Habit) => void;
    isCompleting?: boolean;
  }) => (
    <div>
      <button type="button" onClick={() => onSelect(habit)}>
        Open {habit.name}
      </button>
      <button type="button" onClick={() => onComplete(habit.id)}>
        Complete {habit.name}
      </button>
      {isCompleting ? <span>Completing {habit.name}</span> : null}
    </div>
  ),
}));

vi.mock("@/components/habits/habit-detail", () => ({
  HabitDetail: ({
    habit,
    onComplete,
    onClose,
    isCompleting,
  }: {
    habit: Habit;
    onComplete: (id: string, note?: string) => void;
    onClose: () => void;
    isCompleting?: boolean;
  }) => (
    <div>
      <div>Detail {habit.name}</div>
      <button type="button" onClick={() => onComplete(habit.id, "Felt strong")}>
        Complete with note
      </button>
      <button type="button" onClick={onClose}>
        Close detail
      </button>
      {isCompleting ? <span>Completing detail</span> : null}
    </div>
  ),
}));

vi.mock("@/components/habits/create-habit-modal", () => ({
  CreateHabitModal: ({
    open,
    onClose,
    onCreate,
    isCreating,
  }: {
    open: boolean;
    onClose: () => void;
    onCreate: (data: CreateHabitData) => void;
    isCreating?: boolean;
  }) =>
    open ? (
      <div>
        <div>Create habit modal</div>
        <button type="button" onClick={onClose}>
          Close modal
        </button>
        <button
          type="button"
          onClick={() =>
            onCreate({
              name: "Run daily",
              frequency: "weekly",
              tags: ["fitness"],
            })
          }
          disabled={isCreating}
        >
          Save habit
        </button>
      </div>
    ) : null,
}));

describe("HabitsPage", () => {
  beforeEach(() => {
    mocks.getHabits.mockReset();
    mocks.createHabit.mockReset();
    mocks.completeHabit.mockReset();
    mocks.toastSuccess.mockReset();
    mocks.toastError.mockReset();
  });

  it("renders stats, completes a habit, selects details, and opens create modal", async () => {
    const user = userEvent.setup();
    const activeHabit = createHabit({
      id: "habit-1",
      name: "Morning meditation",
      current_streak: 5,
      longest_streak: 9,
      total_completions: 14,
      last_completed_at: "2026-04-08T08:00:00Z",
      tags: ["mindfulness"],
    });
    const inactiveHabit = createHabit({
      id: "habit-2",
      name: "Inactive habit",
      active: false,
    });

    mocks.getHabits.mockResolvedValue([activeHabit, inactiveHabit]);
    mocks.createHabit.mockResolvedValue(createHabit({ id: "habit-3" }));
    mocks.completeHabit.mockResolvedValue({
      id: "log-1",
      habit_id: "habit-1",
      completed_at: "2026-04-08T12:00:00Z",
      note: "Felt strong",
      source: "manual",
    });

    renderWithProviders(<HabitsPage />);

    expect(await screen.findByRole("heading", { name: "Habits" })).toBeInTheDocument();
    expect(await screen.findByText("Active Habits")).toBeInTheDocument();
    expect(screen.getByText("Completed Today")).toBeInTheDocument();
    expect(screen.getByText("Best Active Streak")).toBeInTheDocument();
    expect(screen.getByText("0 / 1")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("Open Morning meditation")).toBeInTheDocument();
    expect(screen.queryByText("Open Inactive habit")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Open Morning meditation" }));
    expect(await screen.findByText("Detail Morning meditation")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Complete with note" }));
    await waitFor(() => {
      expect(mocks.completeHabit).toHaveBeenCalledWith("habit-1", "Felt strong");
    });

    await user.click(screen.getByRole("button", { name: "Close detail" }));
    expect(await screen.findByText("Open Morning meditation")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "New Habit" }));
    expect(await screen.findByText("Create habit modal")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save habit" }));

    await waitFor(() => {
      expect(mocks.createHabit).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Run daily",
          frequency: "weekly",
          tags: ["fitness"],
        }),
        expect.anything(),
      );
    });
    expect(mocks.toastSuccess).toHaveBeenCalled();
  });

  it("renders loading state while habits are pending", () => {
    mocks.getHabits.mockReturnValue(new Promise(() => {}));

    const { container } = renderWithProviders(<HabitsPage />);

    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });

  it("renders the error state when habits fail to load", async () => {
    mocks.getHabits.mockRejectedValue(new Error("habits failed"));

    renderWithProviders(<HabitsPage />);

    expect(await screen.findByText("Page Error: habits failed")).toBeInTheDocument();
  });

  it("renders the empty state when no habits exist", async () => {
    mocks.getHabits.mockResolvedValue([]);

    renderWithProviders(<HabitsPage />);

    expect(await screen.findByText("No habits yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create Your First Habit" })).toBeInTheDocument();
  });

  it("retries after a habits load failure and closes the create modal through the page shell", async () => {
    const user = userEvent.setup();
    mocks.getHabits.mockRejectedValueOnce(new Error("habits failed")).mockResolvedValueOnce([]);

    renderWithProviders(<HabitsPage />);

    expect(await screen.findByText("Page Error: habits failed")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("No habits yet")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Create Your First Habit" }));
    expect(await screen.findByText("Create habit modal")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Close modal" }));
    expect(screen.queryByText("Create habit modal")).not.toBeInTheDocument();
  });

  it("surfaces create and complete errors, and shows the in-flight quick-complete state", async () => {
    const user = userEvent.setup();
    const activeHabit = createHabit({
      id: "habit-1",
      name: "Morning meditation",
      current_streak: 5,
      longest_streak: 9,
      total_completions: 14,
      last_completed_at: null,
      tags: ["mindfulness"],
    });

    const pendingComplete = new Promise(() => {});

    mocks.getHabits.mockResolvedValue([activeHabit]);
    mocks.createHabit.mockRejectedValue({ message: "create failed" });
    mocks.completeHabit
      .mockReturnValueOnce(pendingComplete)
      .mockRejectedValueOnce({ message: "complete failed" });

    renderWithProviders(<HabitsPage />);

    expect(
      await screen.findByRole("button", { name: "Complete Morning meditation" }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Complete Morning meditation" }));
    expect(await screen.findByText("Completing Morning meditation")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Open Morning meditation" }));
    await user.click(screen.getByRole("button", { name: "Complete with note" }));

    await waitFor(() => {
      expect(mocks.completeHabit).toHaveBeenLastCalledWith("habit-1", "Felt strong");
    });
    await waitFor(() => {
      expect(mocks.toastError).toHaveBeenCalledWith("complete failed");
    });

    await user.click(screen.getByRole("button", { name: "New Habit" }));
    await user.click(screen.getByRole("button", { name: "Save habit" }));

    await waitFor(() => {
      expect(mocks.toastError).toHaveBeenCalledWith("create failed");
    });
  });
});

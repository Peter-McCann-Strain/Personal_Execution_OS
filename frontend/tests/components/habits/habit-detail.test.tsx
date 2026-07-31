import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent, waitFor } from "../../test-utils";
import { HabitDetail } from "@/components/habits/habit-detail";
import { createHabit, createHabitLog } from "../../factories";

const mocks = vi.hoisted(() => ({
  getHabitLogs: vi.fn(),
}));

vi.mock("@/api/habits", () => ({
  getHabitLogs: mocks.getHabitLogs,
}));

describe("HabitDetail", () => {
  beforeEach(() => {
    mocks.getHabitLogs.mockReset();
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-04-08T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders loading skeletons while logs are pending", () => {
    mocks.getHabitLogs.mockReturnValue(new Promise(() => {}));

    const { container } = renderWithProviders(
      <HabitDetail habit={createHabit()} onComplete={vi.fn()} onClose={vi.fn()} />,
    );

    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });

  it("renders logs, completion rate, and forwards note completions", async () => {
    const user = userEvent.setup();
    const onComplete = vi.fn();

    mocks.getHabitLogs.mockResolvedValue([
      createHabitLog({
        id: "habit-log-1",
        completed_at: "2026-04-08T08:00:00Z",
        note: "Morning done",
      }),
      createHabitLog({
        id: "habit-log-2",
        completed_at: "2026-04-07T08:00:00Z",
        note: null,
      }),
    ]);

    renderWithProviders(
      <HabitDetail
        habit={createHabit({
          current_streak: 6,
          longest_streak: 8,
          total_completions: 12,
          last_completed_at: "2026-04-07T08:00:00Z",
        })}
        onComplete={onComplete}
        onClose={vi.fn()}
      />,
    );

    expect(await screen.findByRole("heading", { name: "Morning meditation" })).toBeInTheDocument();
    expect(await screen.findByText("Morning done")).toBeInTheDocument();
    expect(screen.getByText("7%")).toBeInTheDocument();

    await user.type(screen.getByPlaceholderText("Optional note..."), "Felt good");
    await user.click(screen.getByRole("button", { name: "Complete" }));

    await waitFor(() => {
      expect(onComplete).toHaveBeenCalledWith("habit-1", "Felt good");
    });
  });

  it("renders the empty completions state when no logs are returned", async () => {
    mocks.getHabitLogs.mockResolvedValue([]);

    renderWithProviders(
      <HabitDetail
        habit={createHabit({
          last_completed_at: null,
        })}
        onComplete={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(await screen.findByText("No completions in the last 30 days")).toBeInTheDocument();
  });

  it("prevents duplicate completion when the habit is already done today", async () => {
    const user = userEvent.setup();
    const onComplete = vi.fn();
    const onClose = vi.fn();

    mocks.getHabitLogs.mockResolvedValue([
      createHabitLog({
        id: "habit-log-3",
        completed_at: "2026-04-08T08:00:00Z",
        note: "Already done",
      }),
    ]);

    renderWithProviders(
      <HabitDetail
        habit={createHabit({
          last_completed_at: "2026-04-08T08:00:00Z",
        })}
        onComplete={onComplete}
        onClose={onClose}
      />,
    );

    expect(await screen.findByRole("button", { name: "Done" })).toBeDisabled();

    await user.type(screen.getByPlaceholderText("Optional note..."), "Try again");
    await user.keyboard("{Enter}");

    expect(onComplete).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("submits without a note and closes the detail panel", async () => {
    const user = userEvent.setup();
    const onComplete = vi.fn();
    const onClose = vi.fn();

    mocks.getHabitLogs.mockResolvedValue([
      createHabitLog({
        id: "habit-log-4",
        completed_at: "2026-04-07T08:00:00Z",
        note: null,
      }),
    ]);

    renderWithProviders(
      <HabitDetail
        habit={createHabit({
          last_completed_at: "2026-04-07T08:00:00Z",
          tags: [],
        })}
        onComplete={onComplete}
        onClose={onClose}
      />,
    );

    await screen.findByRole("heading", { name: "Morning meditation" });

    await user.click(screen.getByRole("button", { name: "Complete" }));
    await waitFor(() => {
      expect(onComplete).toHaveBeenCalledWith("habit-1", undefined);
    });

    await user.click(screen.getByRole("button", { name: "Close detail" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("renders custom frequency text and supports Enter-to-complete", async () => {
    const user = userEvent.setup();
    const onComplete = vi.fn();

    mocks.getHabitLogs.mockResolvedValue([
      createHabitLog({
        id: "habit-log-5",
        completed_at: "2026-04-06T08:00:00Z",
        note: null,
      }),
    ]);

    renderWithProviders(
      <HabitDetail
        habit={createHabit({
          frequency: "custom",
          frequency_days: 3,
          last_completed_at: null,
          tags: [],
        })}
        onComplete={onComplete}
        onClose={vi.fn()}
      />,
    );

    expect(await screen.findByText("Every 3 days")).toBeInTheDocument();

    await user.type(screen.getByPlaceholderText("Optional note..."), "Done");
    await user.keyboard("{Enter}");

    await waitFor(() => {
      expect(onComplete).toHaveBeenCalledWith("habit-1", "Done");
    });
  });

  it("renders the no-history state when logs resolve to null", async () => {
    mocks.getHabitLogs.mockResolvedValue(null as never);

    renderWithProviders(
      <HabitDetail
        habit={createHabit({
          last_completed_at: "2026-04-07T08:00:00Z",
        })}
        onComplete={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(await screen.findByRole("heading", { name: "Morning meditation" })).toBeInTheDocument();
    expect(screen.queryByText("Recent Completions (1)")).not.toBeInTheDocument();
    expect(screen.queryByText("No completions in the last 30 days")).not.toBeInTheDocument();
  });
});

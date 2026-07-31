import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent } from "@testing-library/react";
import { renderWithProviders, screen } from "../../test-utils";
import { HabitCard } from "@/components/habits/habit-card";
import { createHabit } from "../../factories";

describe("HabitCard", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-04-08T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders completed-today state and forwards selection", async () => {
    const onComplete = vi.fn();
    const onSelect = vi.fn();

    renderWithProviders(
      <HabitCard
        habit={createHabit({
          name: "Morning meditation",
          last_completed_at: "2026-04-08T08:00:00Z",
          current_streak: 6,
          longest_streak: 8,
          total_completions: 12,
        })}
        onComplete={onComplete}
        onSelect={onSelect}
      />,
    );

    expect(screen.getByText("Morning meditation")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Done Today" })).toBeDisabled();

    screen.getByText("Morning meditation").click();
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: "habit-1" }));
    expect(onComplete).not.toHaveBeenCalled();
  });

  it("renders custom frequency and forwards quick completion", async () => {
    const onComplete = vi.fn();
    const onSelect = vi.fn();

    renderWithProviders(
      <HabitCard
        habit={createHabit({
          id: "habit-2",
          name: "Deep work",
          description: null,
          frequency: "custom",
          frequency_days: 3,
          last_completed_at: null,
          current_streak: 0,
          longest_streak: 0,
          tags: [],
        })}
        onComplete={onComplete}
        onSelect={onSelect}
      />,
    );

    expect(screen.getByText("Every 3d")).toBeInTheDocument();

    screen.getByRole("button", { name: "Complete" }).click();

    expect(onComplete).toHaveBeenCalledWith("habit-2");
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("renders the daily success state with tags and forwards selection", () => {
    const onComplete = vi.fn();
    const onSelect = vi.fn();

    renderWithProviders(
      <HabitCard
        habit={createHabit({
          id: "habit-3",
          name: "Deep work",
          description: null,
          frequency: "daily",
          frequency_days: 1,
          current_streak: 8,
          longest_streak: 10,
          total_completions: 25,
          last_completed_at: "2026-04-07T08:00:00Z",
          tags: ["focus", "work"],
        })}
        onComplete={onComplete}
        onSelect={onSelect}
      />,
    );

    expect(screen.getByText("Daily")).toBeInTheDocument();
    expect(screen.getByText("focus")).toBeInTheDocument();
    expect(screen.getByText("work")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Deep work"));
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: "habit-3" }));
    fireEvent.click(screen.getByRole("button", { name: "Complete" }));
    expect(onComplete).toHaveBeenCalledWith("habit-3");
  });

  it("renders the warning and default streak states for weekly and monthly habits", () => {
    const onComplete = vi.fn();
    const onSelect = vi.fn();

    const { rerender } = renderWithProviders(
      <HabitCard
        habit={createHabit({
          id: "habit-4",
          name: "Weekly review",
          frequency: "weekly",
          frequency_days: 7,
          current_streak: 2,
          longest_streak: 5,
          total_completions: 9,
          last_completed_at: null,
          tags: [],
        })}
        onComplete={onComplete}
        onSelect={onSelect}
      />,
    );

    expect(screen.getByText("Weekly")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Complete" }));
    expect(onComplete).toHaveBeenCalledWith("habit-4");

    rerender(
      <HabitCard
        habit={createHabit({
          id: "habit-5",
          name: "Monthly review",
          frequency: "monthly",
          frequency_days: null,
          current_streak: 1,
          longest_streak: 8,
          total_completions: 3,
          last_completed_at: null,
          tags: [],
        })}
        onComplete={onComplete}
        onSelect={onSelect}
      />,
    );

    expect(screen.getByText("Monthly")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Monthly review"));
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: "habit-5" }));
  });
});

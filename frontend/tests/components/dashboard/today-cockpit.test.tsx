import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent, waitFor, within } from "../../test-utils";
import { createGoal, createHabit } from "../../factories";
import { TodayCockpit } from "@/components/dashboard/today-cockpit";
import type { Habit } from "@/api/habits";
import type { CalendarEvent, Commitment, Goal } from "@/types";

const mocks = vi.hoisted(() => ({
  completeHabit: vi.fn(),
  getActiveGoals: vi.fn(),
  getEvents: vi.fn(),
  getHabits: vi.fn(),
  getOpenCommitments: vi.fn(),
  getOverdueCommitments: vi.fn(),
  navigate: vi.fn(),
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
  updateCommitmentStatus: vi.fn(),
}));

vi.mock("react-router", async () => {
  const actual = await vi.importActual<typeof import("react-router")>("react-router");
  return {
    ...actual,
    useNavigate: () => mocks.navigate,
  };
});

vi.mock("sonner", () => ({
  toast: {
    error: mocks.toastError,
    success: mocks.toastSuccess,
  },
}));

vi.mock("@/api/calendar", () => ({
  getEvents: mocks.getEvents,
}));

vi.mock("@/api/dashboard", () => ({
  getActiveGoals: mocks.getActiveGoals,
}));

vi.mock("@/api/commitments", () => ({
  getOpenCommitments: mocks.getOpenCommitments,
  getOverdueCommitments: mocks.getOverdueCommitments,
  updateCommitmentStatus: mocks.updateCommitmentStatus,
}));

vi.mock("@/api/habits", () => ({
  completeHabit: mocks.completeHabit,
  getHabits: mocks.getHabits,
}));

function localIso(day: number, hour: number, minute = 0): string {
  return new Date(2026, 3, day, hour, minute).toISOString();
}

function createEvent(overrides: Partial<CalendarEvent> = {}): CalendarEvent {
  return {
    id: "event-1",
    summary: "Planning review",
    start: localIso(8, 10),
    end: localIso(8, 11),
    location: null,
    description: null,
    attendees: [],
    ...overrides,
  };
}

function createCommitment(overrides: Partial<Commitment> = {}): Commitment {
  return {
    id: "commitment-1",
    verbatim_text: "I will send the project update.",
    normalized_action: "Send the project update",
    who_committed: "Alex",
    who_to: "Team",
    temporal_expression_raw: "tomorrow",
    temporal_normalized: localIso(9, 9),
    commitment_type: "promise",
    confidence_score: 0.9,
    status: "acknowledged",
    created_at: localIso(7, 9),
    updated_at: localIso(7, 9),
    ...overrides,
  };
}

function setResolvedQueries({
  commitments = [],
  events = [],
  goals = [],
  habits = [],
  overdue = [],
}: {
  commitments?: Commitment[];
  events?: CalendarEvent[];
  goals?: Goal[];
  habits?: Habit[];
  overdue?: Commitment[];
} = {}): void {
  mocks.getEvents.mockResolvedValue(events);
  mocks.getOpenCommitments.mockResolvedValue(commitments);
  mocks.getOverdueCommitments.mockResolvedValue(overdue);
  mocks.getHabits.mockResolvedValue(habits);
  mocks.getActiveGoals.mockResolvedValue(goals);
}

function expectCount(label: string, value: string): void {
  const labelNode = screen
    .getAllByText(label)
    .find((node) => node.parentElement?.textContent === `${value}${label}`);
  const pill = labelNode?.parentElement;
  expect(pill).toBeDefined();
  expect(within(pill as HTMLElement).getByText(value)).toBeInTheDocument();
}

describe("TodayCockpit", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 3, 8, 10, 30));

    for (const mock of Object.values(mocks)) {
      mock.mockReset();
    }

    setResolvedQueries();
    mocks.updateCommitmentStatus.mockResolvedValue(createCommitment({ status: "completed" }));
    mocks.completeHabit.mockResolvedValue({
      id: "habit-log-1",
      habit_id: "habit-1",
      completed_at: localIso(8, 10, 30),
      note: null,
      source: "manual",
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the cockpit skeleton until every dashboard query has settled", () => {
    mocks.getEvents.mockReturnValue(new Promise<CalendarEvent[]>(() => {}));

    const { container } = renderWithProviders(<TodayCockpit />);

    expect(container.querySelectorAll(".animate-pulse")).toHaveLength(5);
    expect(screen.queryByRole("heading", { name: "Today" })).not.toBeInTheDocument();
  });

  it("keeps the cockpit usable while calendar, commitment, habit, and goal queries fail", async () => {
    mocks.getEvents.mockRejectedValue(new Error("calendar failed"));
    mocks.getOpenCommitments.mockRejectedValue(new Error("open commitments failed"));
    mocks.getOverdueCommitments.mockRejectedValue(new Error("overdue commitments failed"));
    mocks.getHabits.mockRejectedValue(new Error("habits failed"));
    mocks.getActiveGoals.mockRejectedValue(new Error("goals failed"));

    renderWithProviders(<TodayCockpit />);

    expect(await screen.findByText("Calendar unavailable.")).toBeInTheDocument();
    expect(screen.getByText("Commitments unavailable.")).toBeInTheDocument();
    expect(screen.getByText("Habits unavailable.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Quick Capture/i })).toBeInTheDocument();
    expect(
      screen.getByText("No urgent commitments, events, or due habits found."),
    ).toBeInTheDocument();
  });

  it("renders the complete empty state and routes its primary, assistant, and section actions", async () => {
    const user = userEvent.setup();

    renderWithProviders(<TodayCockpit />);

    expect(await screen.findByRole("heading", { name: "Today" })).toBeInTheDocument();
    expect(screen.getByText(/Wednesday 8 April/)).toBeInTheDocument();
    expectCount("Events", "0");
    expectCount("Due habits", "0");
    expectCount("Overdue", "0");
    expect(screen.getByText("No events today.")).toBeInTheDocument();
    expect(screen.getByText("No open commitments.")).toBeInTheDocument();
    expect(screen.getByText("Routines are clear for today.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Quick Capture/i }));
    await user.click(screen.getByRole("button", { name: "Ask Assistant" }));

    const viewButtons = screen.getAllByRole("button", { name: "View" });
    await user.click(viewButtons[0]);
    await user.click(viewButtons[1]);
    await user.click(viewButtons[2]);

    expect(mocks.navigate).toHaveBeenNthCalledWith(1, "/diary?capture=1");
    expect(mocks.navigate).toHaveBeenNthCalledWith(
      2,
      `/chat?prompt=${encodeURIComponent(
        "Help me plan today from my schedule, commitments, habits, and goals.",
      )}`,
    );
    expect(mocks.navigate).toHaveBeenNthCalledWith(3, "/calendar");
    expect(mocks.navigate).toHaveBeenNthCalledWith(4, "/commitments");
    expect(mocks.navigate).toHaveBeenNthCalledWith(5, "/habits");
  });

  it("renders populated, sorted data; removes duplicate commitments; and completes row items", async () => {
    const user = userEvent.setup();
    const overdue = createCommitment({
      id: "commitment-overdue",
      normalized_action: "Submit the overdue tax return",
      temporal_expression_raw: "yesterday",
      temporal_normalized: localIso(7, 8),
    });
    const undated = createCommitment({
      id: "commitment-undated",
      normalized_action: "",
      verbatim_text: "Call the insurance provider",
      temporal_expression_raw: "next week",
      temporal_normalized: null,
    });

    setResolvedQueries({
      events: [
        createEvent({
          id: "event-later",
          summary: "Afternoon planning",
          start: localIso(8, 14),
          end: localIso(8, 15),
        }),
        createEvent({
          id: "event-now",
          summary: "Current design review",
          start: localIso(8, 10),
          end: localIso(8, 11),
        }),
      ],
      overdue: [overdue],
      commitments: [undated, overdue],
      habits: [
        createHabit({ id: "habit-daily", name: "Morning stretch", last_completed_at: null }),
        createHabit({
          id: "habit-daily-overdue",
          name: "Daily planning",
          last_completed_at: localIso(7, 8),
        }),
        createHabit({
          id: "habit-weekly",
          name: "Weekly review",
          frequency: "weekly",
          frequency_days: 7,
          last_completed_at: localIso(1, 8),
        }),
        createHabit({
          id: "habit-monthly",
          name: "Monthly finances",
          frequency: "monthly",
          frequency_days: 30,
          last_completed_at: new Date(2026, 2, 1, 8).toISOString(),
        }),
        createHabit({
          id: "habit-custom",
          name: "Custom routine",
          frequency: "custom",
          frequency_days: 2,
          last_completed_at: localIso(5, 8),
        }),
        createHabit({
          id: "habit-invalid",
          name: "Routine with stale data",
          last_completed_at: "not-a-date",
        }),
        createHabit({
          id: "habit-done",
          name: "Already completed",
          last_completed_at: localIso(8, 8),
        }),
        createHabit({
          id: "habit-inactive",
          name: "Inactive routine",
          active: false,
          last_completed_at: null,
        }),
      ],
      goals: [createGoal()],
    });

    renderWithProviders(<TodayCockpit />);

    expect(await screen.findByRole("heading", { name: "Today" })).toBeInTheDocument();
    expectCount("Events", "2");
    expectCount("Due habits", "6");
    expectCount("Overdue", "1");
    expect(screen.getAllByText("Submit the overdue tax return")).toHaveLength(2);
    expect(screen.getByText("Call the insurance provider")).toBeInTheDocument();
    expect(screen.getByText("next week")).toBeInTheDocument();
    expect(screen.getByText("Current design review")).toBeInTheDocument();
    expect(screen.getByText("Now")).toBeInTheDocument();
    expect(screen.getByText("Morning stretch")).toBeInTheDocument();
    expect(screen.queryByText("Custom routine")).not.toBeInTheDocument();
    expect(screen.queryByText("Already completed")).not.toBeInTheDocument();
    expect(screen.queryByText("Inactive routine")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Mark Done/i }));
    await waitFor(() => {
      expect(mocks.updateCommitmentStatus).toHaveBeenCalledWith("commitment-overdue", "completed");
    });
    expect(mocks.toastSuccess).toHaveBeenCalledWith("Commitment marked complete");

    await user.click(screen.getAllByRole("button", { name: "Complete" })[0]);
    await waitFor(() => {
      expect(mocks.completeHabit).toHaveBeenCalledWith("habit-daily");
    });
    expect(mocks.toastSuccess).toHaveBeenCalledWith("Habit completed");
  });

  it("surfaces useful mutation errors without removing the actionable rows", async () => {
    const user = userEvent.setup();
    const overdue = createCommitment({
      id: "commitment-overdue",
      normalized_action: "Recover the overdue action",
      temporal_normalized: localIso(7, 8),
    });
    setResolvedQueries({
      overdue: [overdue],
      commitments: [overdue],
      habits: [createHabit({ id: "habit-1", name: "Take a walk", last_completed_at: null })],
    });
    mocks.updateCommitmentStatus.mockRejectedValue(new Error("Commitment service is offline"));
    mocks.completeHabit.mockRejectedValue({ reason: "offline" });

    renderWithProviders(<TodayCockpit />);

    expect(await screen.findAllByText("Recover the overdue action")).toHaveLength(2);

    await user.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => {
      expect(mocks.toastError).toHaveBeenCalledWith("Commitment service is offline");
    });

    await user.click(screen.getByRole("button", { name: "Complete" }));
    await waitFor(() => {
      expect(mocks.toastError).toHaveBeenCalledWith("Failed to complete habit");
    });

    expect(screen.getAllByText("Recover the overdue action")).toHaveLength(2);
    expect(screen.getByText("Take a walk")).toBeInTheDocument();
  });

  it("chooses a due-today commitment before events, habits, and goals", async () => {
    const user = userEvent.setup();
    const dueToday = createCommitment({
      id: "commitment-today",
      normalized_action: "Send today's handover",
      temporal_normalized: localIso(8, 16),
    });
    setResolvedQueries({
      commitments: [dueToday],
      events: [createEvent()],
      habits: [createHabit({ last_completed_at: null })],
      goals: [createGoal()],
    });

    renderWithProviders(<TodayCockpit />);

    expect(
      await screen.findByRole("heading", { name: "Send today's handover" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Due today")).toHaveLength(3);

    await user.click(screen.getByRole("button", { name: /Mark Done/i }));
    await waitFor(() => {
      expect(mocks.updateCommitmentStatus).toHaveBeenCalledWith("commitment-today", "completed");
    });
  });

  it("opens the calendar for the next valid event and tolerates malformed event dates", async () => {
    const user = userEvent.setup();
    setResolvedQueries({
      events: [
        createEvent({
          id: "event-invalid",
          summary: "Imported event with invalid dates",
          start: "not-a-date",
          end: "not-a-date",
        }),
        createEvent({
          id: "event-next",
          summary: "Roadmap workshop",
          start: localIso(8, 12),
          end: localIso(8, 13),
        }),
      ],
    });

    renderWithProviders(<TodayCockpit />);

    expect(await screen.findByRole("heading", { name: "Roadmap workshop" })).toBeInTheDocument();
    expect(screen.getAllByText("--:-----:--")).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: /Open Calendar/i }));
    expect(mocks.navigate).toHaveBeenCalledWith("/calendar");
  });

  it("promotes a due habit when the schedule is clear and completes it from the hero", async () => {
    const user = userEvent.setup();
    setResolvedQueries({
      habits: [
        createHabit({
          id: "habit-custom",
          name: "Write the daily reflection",
          frequency: "custom",
          frequency_days: 0,
          current_streak: 6,
          last_completed_at: localIso(6, 8),
        }),
      ],
      goals: [createGoal()],
    });

    renderWithProviders(<TodayCockpit />);

    expect(
      await screen.findByRole("heading", { name: "Write the daily reflection" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("6 day streak")).toHaveLength(2);

    await user.click(screen.getByRole("button", { name: /Complete Habit/i }));
    await waitFor(() => {
      expect(mocks.completeHabit).toHaveBeenCalledWith("habit-custom");
    });
  });

  it("falls through completed goals, normalizes fractional progress, and opens active goals", async () => {
    const user = userEvent.setup();
    setResolvedQueries({
      goals: [
        createGoal({ id: "goal-complete", title: "Already shipped", progress: 100 }),
        createGoal({
          id: "goal-active",
          title: "Launch the public preview",
          progress: 0.42,
        }),
      ],
    });

    renderWithProviders(<TodayCockpit />);

    expect(
      await screen.findByRole("heading", { name: "Launch the public preview" }),
    ).toBeInTheDocument();
    expect(screen.getByText("42% complete")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Open Goals/i }));
    expect(mocks.navigate).toHaveBeenCalledWith("/goals");
  });
});

import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent, waitFor, within } from "../test-utils";
import { WorkbenchPage } from "@/pages/workbench";
import {
  createEpic,
  createGoal,
  createHabit,
  createMilestone,
  createNote,
  createPaginatedResponse,
  createProject,
  createTask,
} from "../factories";
import type { CalendarEvent, Commitment } from "@/types";

const mocks = vi.hoisted(() => ({
  getEvents: vi.fn(),
  getOpenCommitments: vi.fn(),
  getOverdueCommitments: vi.fn(),
  getGoals: vi.fn(),
  getHabits: vi.fn(),
  listNotes: vi.fn(),
  getProjects: vi.fn(),
  navigate: vi.fn(),
}));

vi.mock("react-router", async (importOriginal) => {
  const original = await importOriginal<typeof import("react-router")>();
  return {
    ...original,
    useNavigate: () => mocks.navigate,
  };
});

vi.mock("@/api/calendar", () => ({
  getEvents: mocks.getEvents,
}));

vi.mock("@/api/commitments", () => ({
  getOpenCommitments: mocks.getOpenCommitments,
  getOverdueCommitments: mocks.getOverdueCommitments,
}));

vi.mock("@/api/goals", () => ({
  getGoals: mocks.getGoals,
}));

vi.mock("@/api/habits", () => ({
  getHabits: mocks.getHabits,
}));

vi.mock("@/api/notes", () => ({
  listNotes: mocks.listNotes,
}));

vi.mock("@/api/projects", () => ({
  getProjects: mocks.getProjects,
}));

vi.mock("@/components/ui/page-transition", () => ({
  PageTransition: ({ children }: { children: React.ReactNode }) => children,
}));

function commitment(overrides: Partial<Commitment> = {}): Commitment {
  return {
    id: "commitment-1",
    verbatim_text: "Send launch brief today",
    normalized_action: "Send launch brief",
    who_committed: "me",
    who_to: "team",
    temporal_expression_raw: "today",
    temporal_normalized: new Date().toISOString(),
    commitment_type: "promise",
    confidence_score: 0.9,
    status: "acknowledged",
    created_at: "2026-04-01T09:00:00Z",
    updated_at: "2026-04-01T09:00:00Z",
    ...overrides,
  };
}

function event(overrides: Partial<CalendarEvent> = {}): CalendarEvent {
  return {
    id: "event-1",
    summary: "Planning review",
    start: new Date().toISOString(),
    end: new Date(Date.now() + 30 * 60 * 1000).toISOString(),
    location: null,
    description: null,
    attendees: [],
    ...overrides,
  };
}

describe("WorkbenchPage", () => {
  beforeEach(() => {
    Object.values(mocks).forEach((mock) => mock.mockReset());

    const task = createTask({
      id: "task-1",
      title: "Add saved view filtering",
      status: "in_progress",
    });
    const project = createProject({
      title: "Workbench build",
      status: "in-progress",
      epics: [
        createEpic({
          milestones: [createMilestone({ tasks: [task] })],
        }),
      ],
    });

    mocks.getEvents.mockResolvedValue([event()]);
    mocks.getOpenCommitments.mockResolvedValue([commitment()]);
    mocks.getOverdueCommitments.mockResolvedValue([
      commitment({
        id: "commitment-overdue",
        normalized_action: "Reply to Maria",
        verbatim_text: "Reply to Maria",
        temporal_expression_raw: "yesterday",
        temporal_normalized: "2026-04-01T09:00:00Z",
      }),
    ]);
    mocks.getGoals.mockResolvedValue(
      createPaginatedResponse([
        createGoal({
          id: "goal-low",
          title: "Low progress goal",
          progress: 0.2,
        }),
      ]),
    );
    mocks.getHabits.mockResolvedValue([
      createHabit({
        name: "Evening review",
        last_completed_at: "2026-04-01T09:00:00Z",
      }),
    ]);
    mocks.listNotes.mockResolvedValue(
      createPaginatedResponse([
        createNote({
          title: "Workbench research note",
          tags: ["workbench"],
        }),
      ]),
    );
    mocks.getProjects.mockResolvedValue(createPaginatedResponse([project]));
  });

  it("renders saved views and switches between list, board, and filtered views", async () => {
    const user = userEvent.setup();
    renderWithProviders(<WorkbenchPage />);

    expect(await screen.findByRole("heading", { name: "Workbench" })).toBeInTheDocument();
    expect(await screen.findByText("Send launch brief")).toBeInTheDocument();
    expect(screen.getByText("Planning review")).toBeInTheDocument();

    await user.click(screen.getByText("At Risk"));
    expect(await screen.findByText("Low progress goal")).toBeInTheDocument();
    expect(screen.getByText("Reply to Maria")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Board" }));
    expect(screen.getAllByText("Overdue").length).toBeGreaterThan(0);

    await user.type(screen.getByPlaceholderText("Filter this view..."), "Maria");
    await waitFor(() => {
      expect(screen.getByText("Reply to Maria")).toBeInTheDocument();
      expect(screen.queryByText("Low progress goal")).not.toBeInTheDocument();
    });
  });

  it("keeps calendar records visible without exposing calendar write actions", async () => {
    renderWithProviders(<WorkbenchPage />);

    expect(await screen.findByRole("heading", { name: "Workbench" })).toBeInTheDocument();
    expect(await screen.findByText("Reply to Maria")).toBeInTheDocument();
    expect(screen.getByText("Planning review")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Schedule" })).not.toBeInTheDocument();
  });

  it("shows placeholders until every source has settled", () => {
    mocks.getProjects.mockReturnValue(new Promise(() => undefined));

    const { container } = renderWithProviders(<WorkbenchPage />);

    expect(container.querySelectorAll(".animate-pulse")).toHaveLength(6);
  });

  it("keeps available records usable when two sources fail", async () => {
    mocks.getGoals.mockRejectedValue(new Error("goals offline"));
    mocks.getProjects.mockRejectedValue(new Error("projects offline"));

    renderWithProviders(<WorkbenchPage />);

    expect(
      await screen.findByText(
        "2 sources unavailable. The workbench is showing the data it could load.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Partial")).toBeInTheDocument();
    expect(screen.getByText("Send launch brief")).toBeInTheDocument();
    expect(screen.getByText("Planning review")).toBeInTheDocument();
  });

  it("shows a clear empty state and can switch to an empty knowledge view", async () => {
    mocks.getEvents.mockResolvedValue([]);
    mocks.getOpenCommitments.mockResolvedValue([]);
    mocks.getOverdueCommitments.mockResolvedValue([]);
    mocks.getGoals.mockResolvedValue(createPaginatedResponse([]));
    mocks.getHabits.mockResolvedValue([]);
    mocks.listNotes.mockResolvedValue(createPaginatedResponse([]));
    mocks.getProjects.mockResolvedValue(createPaginatedResponse([]));
    const user = userEvent.setup();

    renderWithProviders(<WorkbenchPage />);

    expect(await screen.findByText("No records in this view")).toBeInTheDocument();
    expect(screen.getByText("0 visible of 0 loaded records")).toBeInTheDocument();
    await user.click(screen.getByText("Knowledge"));
    expect(screen.getByRole("heading", { name: "Knowledge" })).toBeInTheDocument();
    expect(screen.getByText("No records in this view")).toBeInTheDocument();
  });

  it("navigates from the assistant, list, board, and timeline views", async () => {
    const user = userEvent.setup();
    renderWithProviders(<WorkbenchPage />);

    await screen.findByText("Send launch brief");
    await user.click(screen.getByRole("button", { name: "Ask Assistant" }));
    expect(mocks.navigate).toHaveBeenCalledWith(
      "/chat?prompt=Review%20my%20workbench%20and%20suggest%20the%20best%20next%20actions%20for%20today.",
    );

    await user.click(screen.getAllByRole("button", { name: "Open" })[0]);
    expect(mocks.navigate).toHaveBeenCalled();

    await user.click(screen.getByRole("tab", { name: "Board" }));
    await user.click(screen.getByRole("button", { name: /Reply to Maria/ }));
    expect(mocks.navigate).toHaveBeenCalledWith("/commitments");
    await user.click(screen.getAllByRole("button", { name: "Open" })[0]);
    expect(mocks.navigate).toHaveBeenCalled();

    await user.click(screen.getByRole("tab", { name: "Timeline" }));
    await user.click(screen.getByRole("button", { name: /Reply to Maria/ }));
    expect(mocks.navigate).toHaveBeenLastCalledWith("/commitments");
  });

  it("classifies consequential statuses across every supported record type", async () => {
    const user = userEvent.setup();
    const day = 24 * 60 * 60 * 1000;
    const now = Date.now();
    const yesterday = new Date(now - day).toISOString();
    const tomorrow = new Date(now + day).toISOString();
    const nextWeek = new Date(now + 7 * day).toISOString();
    const lastWeek = new Date(now - 7 * day).toISOString();
    const ongoingStart = new Date(now - 5 * 60 * 1000).toISOString();
    const ongoingEnd = new Date(now + 25 * 60 * 1000).toISOString();

    const projectWithTask = (
      title: string,
      projectId: string,
      task: ReturnType<typeof createTask>,
      overrides: Parameters<typeof createProject>[0] = {},
    ) =>
      createProject({
        id: projectId,
        title,
        deadline: null,
        status: "in-progress",
        epics: [
          createEpic({
            id: `epic-${projectId}`,
            milestones: [
              createMilestone({
                id: `milestone-${projectId}`,
                tasks: [task],
              }),
            ],
          }),
        ],
        ...overrides,
      });

    mocks.getProjects.mockResolvedValue(
      createPaginatedResponse([
        projectWithTask(
          "Completed project",
          "completed",
          createTask({ id: "done-task", title: "Finished task", status: "done" }),
          { status: "completed" },
        ),
        projectWithTask(
          "Blocked project",
          "blocked",
          createTask({ id: "blocked-task", title: "Blocked task", status: "blocked" }),
        ),
        projectWithTask(
          "Overdue project",
          "overdue",
          createTask({ id: "overdue-task", title: "Overdue task", status: "in_progress" }),
          { deadline: yesterday },
        ),
        createProject({
          id: "planning",
          title: "Planning project",
          deadline: null,
          status: "planning",
          appetite: null,
          epics: [],
        }),
        projectWithTask(
          "Active project",
          "active",
          createTask({ id: "backlog-task", title: "Backlog task", status: "backlog" }),
        ),
        projectWithTask(
          "Active task project",
          "active-task",
          createTask({ id: "active-task", title: "Active task", status: "in_progress" }),
        ),
      ]),
    );
    mocks.getOpenCommitments.mockResolvedValue([
      commitment({
        id: "commitment-done",
        normalized_action: "Completed promise",
        status: "completed",
        temporal_normalized: null,
      }),
      commitment({
        id: "commitment-cancelled",
        normalized_action: "Cancelled promise",
        status: "cancelled",
        temporal_normalized: null,
      }),
      commitment({
        id: "commitment-detected",
        normalized_action: "Detected promise",
        status: "detected",
        temporal_normalized: nextWeek,
      }),
      commitment({
        id: "commitment-active",
        normalized_action: "",
        verbatim_text: "Unscheduled active promise",
        status: "acknowledged",
        temporal_normalized: null,
        temporal_expression_raw: null,
      }),
    ]);
    mocks.getOverdueCommitments.mockResolvedValue([
      commitment({
        id: "commitment-overdue",
        normalized_action: "Overdue promise",
        temporal_normalized: yesterday,
      }),
      commitment({
        id: "commitment-due",
        normalized_action: "Due promise",
        temporal_normalized: tomorrow,
      }),
      commitment({
        id: "commitment-active",
        normalized_action: "",
        verbatim_text: "Unscheduled active promise",
        temporal_normalized: null,
      }),
    ]);
    mocks.getGoals.mockResolvedValue(
      createPaginatedResponse([
        createGoal({
          id: "goal-done",
          title: "Completed goal",
          status: "completed",
          deadline: null,
        }),
        createGoal({
          id: "goal-overdue",
          title: "Overdue goal",
          deadline: yesterday,
        }),
        createGoal({
          id: "goal-waiting",
          title: "Waiting goal",
          progress: 0.1,
          deadline: null,
        }),
        createGoal({
          id: "goal-active",
          title: "Active goal",
          progress: 80,
          goal_type: null,
          deadline: null,
        }),
      ]),
    );
    mocks.getHabits.mockResolvedValue([
      createHabit({
        id: "habit-inactive",
        name: "Inactive habit",
        active: false,
        last_completed_at: null,
      }),
      createHabit({
        id: "habit-new",
        name: "New due habit",
        last_completed_at: null,
      }),
      createHabit({
        id: "habit-invalid",
        name: "Invalid date habit",
        last_completed_at: "not-a-date",
      }),
      createHabit({
        id: "habit-current",
        name: "Current habit",
        last_completed_at: new Date().toISOString(),
      }),
      createHabit({
        id: "habit-weekly",
        name: "Weekly due habit",
        frequency: "weekly",
        last_completed_at: lastWeek,
      }),
      createHabit({
        id: "habit-monthly",
        name: "Monthly current habit",
        frequency: "monthly",
        last_completed_at: lastWeek,
      }),
      createHabit({
        id: "habit-custom",
        name: "Custom due habit",
        frequency: "custom",
        frequency_days: null,
        last_completed_at: yesterday,
      }),
    ]);
    mocks.getEvents.mockResolvedValue([
      event({
        id: "event-done",
        summary: "Finished meeting",
        start: new Date(now - 2 * 60 * 60 * 1000).toISOString(),
        end: new Date(now - 60 * 60 * 1000).toISOString(),
      }),
      event({
        id: "event-due",
        summary: "Current meeting",
        start: ongoingStart,
        end: ongoingEnd,
      }),
      event({
        id: "event-future",
        summary: "Future meeting",
        start: nextWeek,
        end: new Date(now + 7 * day + 60 * 60 * 1000).toISOString(),
      }),
      event({
        id: "event-invalid",
        summary: "Undated meeting",
        start: "not-a-date",
        end: "not-a-date",
      }),
    ]);
    mocks.listNotes.mockResolvedValue(
      createPaginatedResponse([
        createNote({
          id: "note-para",
          title: "PARA note",
        }),
        createNote({
          id: "note-kind",
          title: "Kind fallback note",
          para_category: null,
          note_type: null,
          kind: "reference",
          executive_summary: null,
          tags: [],
        }),
      ]),
    );

    renderWithProviders(<WorkbenchPage />);

    await screen.findByText("Overdue promise");
    await user.click(screen.getByText("All"));

    const expectStatus = (title: string, status: string) => {
      const row = screen.getByText(title).closest("div.grid");
      expect(row).not.toBeNull();
      expect(within(row!).getByText(status)).toBeInTheDocument();
    };

    expectStatus("Completed project", "done");
    expectStatus("Blocked project", "blocked");
    expectStatus("Overdue project", "overdue");
    expectStatus("Planning project", "waiting");
    expectStatus("Completed promise", "done");
    expectStatus("Detected promise", "waiting");
    expectStatus("Unscheduled active promise", "active");
    expectStatus("Completed goal", "done");
    expectStatus("Waiting goal", "waiting");
    expectStatus("Active goal", "active");
    expectStatus("Inactive habit", "active");
    expectStatus("New due habit", "due");
    expectStatus("Current habit", "active");
    expectStatus("Finished meeting", "done");
    expectStatus("Current meeting", "due");
    expectStatus("Future meeting", "scheduled");
    expectStatus("Undated meeting", "scheduled");

    await user.click(screen.getByText("Projects"));
    expect(screen.getByText("Blocked task")).toBeInTheDocument();
    expect(screen.queryByText("Finished meeting")).not.toBeInTheDocument();
    await user.click(screen.getByText("Knowledge"));
    expect(screen.getByText("PARA note")).toBeInTheDocument();
    expect(screen.getByText("Kind fallback note")).toBeInTheDocument();
  });
});

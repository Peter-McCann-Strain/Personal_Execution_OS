import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent, waitFor } from "../test-utils";
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
}));

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
});

import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent } from "../../test-utils";
import { ProjectTree } from "@/components/projects/project-tree";
import { createEpic, createMilestone, createProject, createTask } from "../../factories";

describe("ProjectTree", () => {
  it("renders an empty state when no epics exist", () => {
    renderWithProviders(<ProjectTree project={createProject()} />);

    expect(screen.getByText("No epics defined yet")).toBeInTheDocument();
  });

  it("supports collapsing, expanding, and forwarding task status changes", async () => {
    const user = userEvent.setup();
    const onTaskStatusChange = vi.fn();

    const task = createTask({
      title: "Ship approvals",
      status: "backlog",
      sort_order: 0,
    });
    const milestone = createMilestone({
      title: "Execution",
      tasks: [task],
    });
    const epic = createEpic({
      title: "Platform",
      milestones: [milestone],
    });

    renderWithProviders(
      <ProjectTree
        project={createProject({ epics: [epic] })}
        onTaskStatusChange={onTaskStatusChange}
      />,
    );

    expect(screen.getByText("Platform")).toBeInTheDocument();
    expect(screen.getByText("Execution")).toBeInTheDocument();
    expect(screen.getByText("Ship approvals")).toBeInTheDocument();

    await user.click(screen.getByText("Collapse All"));
    expect(screen.queryByText("Ship approvals")).not.toBeInTheDocument();

    await user.click(screen.getByText("Expand All"));
    expect(screen.getByText("Ship approvals")).toBeInTheDocument();

    await user.click(screen.getByText("Backlog"));
    expect(onTaskStatusChange).toHaveBeenCalledWith("task-1", "ready");
  });

  it("keeps epics, milestones, and tasks in sort order while toggling individual nodes", async () => {
    const user = userEvent.setup();

    const alphaTaskLate = createTask({
      id: "task-alpha-late",
      title: "Alpha late",
      sort_order: 2,
    });
    const alphaTaskEarly = createTask({
      id: "task-alpha-early",
      title: "Alpha early",
      sort_order: 0,
    });
    const betaTask = createTask({
      id: "task-beta",
      title: "Beta task",
      sort_order: 0,
    });

    const alphaMilestone = createMilestone({
      id: "milestone-alpha",
      title: "Alpha milestone",
      sort_order: 0,
      tasks: [alphaTaskLate, alphaTaskEarly],
    });
    const betaMilestone = createMilestone({
      id: "milestone-beta",
      title: "Beta milestone",
      sort_order: 1,
      tasks: [betaTask],
    });

    const alphaEpic = createEpic({
      id: "epic-alpha",
      title: "Alpha epic",
      sort_order: 0,
      milestones: [alphaMilestone, betaMilestone],
    });
    const betaEpic = createEpic({
      id: "epic-beta",
      title: "Beta epic",
      sort_order: 1,
      milestones: [],
    });

    renderWithProviders(<ProjectTree project={createProject({ epics: [betaEpic, alphaEpic] })} />);

    const epicButtons = screen.getAllByRole("button", { name: /epic/i });
    expect(epicButtons[0]).toHaveTextContent("Alpha epic");
    expect(epicButtons[1]).toHaveTextContent("Beta epic");

    const milestoneButtons = screen.getAllByRole("button", { name: /milestone/i });
    expect(milestoneButtons[0]).toHaveTextContent("Alpha milestone");
    expect(milestoneButtons[1]).toHaveTextContent("Beta milestone");

    expect(screen.getAllByText("Alpha early")[0]).toBeInTheDocument();
    expect(screen.getAllByText("Alpha late")[0]).toBeInTheDocument();
    expect(screen.getByText("Beta task")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Alpha epic/i }));
    expect(screen.queryByText("Alpha early")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Alpha epic/i }));
    expect(screen.getByText("Alpha early")).toBeInTheDocument();
  });

  it("shows zero progress when a milestone has no tasks", () => {
    const emptyMilestone = createMilestone({
      id: "milestone-empty",
      title: "Discovery",
      sort_order: 0,
      tasks: [],
    });
    const epic = createEpic({
      id: "epic-zero",
      title: "Zero progress",
      sort_order: 0,
      milestones: [emptyMilestone],
    });

    renderWithProviders(<ProjectTree project={createProject({ epics: [epic] })} />);

    expect(screen.getByRole("button", { name: /Zero progress/i })).toHaveTextContent("0%");
    expect(screen.getByRole("button", { name: /Discovery/i })).toHaveTextContent("0%");
  });

  it("toggles milestone children independently from epics", async () => {
    const user = userEvent.setup();

    const task = createTask({
      id: "task-toggle",
      title: "Milestone task",
      status: "backlog",
      sort_order: 0,
    });
    const milestone = createMilestone({
      id: "milestone-toggle",
      title: "Milestone toggle",
      sort_order: 0,
      tasks: [task],
    });
    const epic = createEpic({
      id: "epic-toggle",
      title: "Epic toggle",
      sort_order: 0,
      milestones: [milestone],
    });

    renderWithProviders(<ProjectTree project={createProject({ epics: [epic] })} />);

    expect(screen.getByText("Milestone task")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Milestone toggle/i }));
    expect(screen.queryByText("Milestone task")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Milestone toggle/i }));
    expect(screen.getByText("Milestone task")).toBeInTheDocument();
  });
});

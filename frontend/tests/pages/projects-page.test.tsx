import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, waitFor } from "@testing-library/react";
import { renderWithProviders, screen, userEvent } from "../test-utils";
import { ProjectsPage } from "@/pages/projects";
import { createPaginatedResponse, createProject } from "../factories";
import type { Project, ProjectDraft, TaskStatus } from "@/types";

const mocks = vi.hoisted(() => ({
  applyProjectDraft: vi.fn(),
  createProject: vi.fn(),
  getProjectDrafts: vi.fn(),
  getProjects: vi.fn(),
  updateTask: vi.fn(),
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
}));

vi.mock("@/api/projects", () => ({
  applyProjectDraft: mocks.applyProjectDraft,
  createProject: mocks.createProject,
  getProjectDrafts: mocks.getProjectDrafts,
  getProjects: mocks.getProjects,
  updateTask: mocks.updateTask,
}));

vi.mock("sonner", () => ({
  toast: {
    error: mocks.toastError,
    success: mocks.toastSuccess,
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
  PageError: ({ message, onRetry }: { message: string; onRetry?: () => void }) => (
    <div>
      <div>Page Error: {message}</div>
      {onRetry ? (
        <button type="button" onClick={onRetry}>
          Retry projects
        </button>
      ) : null}
    </div>
  ),
}));

vi.mock("@/components/ui/skeleton", () => ({
  Skeleton: () => <div>Skeleton</div>,
}));

vi.mock("@/components/ui/empty-state", () => ({
  EmptyState: ({
    action,
    description,
    title,
  }: {
    action?: { label: string; onClick: () => void };
    description?: string;
    title: string;
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

vi.mock("@/components/projects/project-card", () => ({
  ProjectCard: ({ onClick, project }: { onClick?: () => void; project: Project }) => (
    <button type="button" onClick={onClick}>
      Open {project.title}
    </button>
  ),
}));

vi.mock("@/components/projects/project-tree", () => ({
  ProjectTree: ({
    onTaskStatusChange,
    project,
  }: {
    onTaskStatusChange?: (taskId: string, status: TaskStatus) => void;
    project: Project;
  }) => (
    <div>
      <div>Tree: {project.title}</div>
      <button type="button" onClick={() => onTaskStatusChange?.("task-1", "done")}>
        Complete task-1
      </button>
    </div>
  ),
}));

describe("ProjectsPage", () => {
  beforeEach(() => {
    mocks.applyProjectDraft.mockReset();
    mocks.createProject.mockReset();
    mocks.getProjectDrafts.mockReset();
    mocks.getProjects.mockReset();
    mocks.updateTask.mockReset();
    mocks.toastError.mockReset();
    mocks.toastSuccess.mockReset();
    mocks.getProjectDrafts.mockResolvedValue(createPaginatedResponse([]));
    mocks.applyProjectDraft.mockResolvedValue(createProject());
    mocks.createProject.mockResolvedValue(createProject());
  });

  function deferred<T>() {
    let resolve!: (value: T) => void;
    let reject!: (reason?: unknown) => void;
    const promise = new Promise<T>((res, rej) => {
      resolve = res;
      reject = rej;
    });
    return { promise, resolve, reject };
  }

  it("renders projects, applies filters and sorting, opens detail view, and updates tasks", async () => {
    const alpha = createProject({
      id: "project-1",
      title: "Alpha",
      status: "planning",
      appetite: "small",
      deadline: null,
      created_at: "2026-04-03T09:00:00Z",
    });
    const beta = createProject({
      id: "project-2",
      title: "Beta",
      status: "completed",
      appetite: "medium",
      deadline: "2026-04-08T12:00:00Z",
      created_at: "2026-04-01T09:00:00Z",
    });
    const gamma = createProject({
      id: "project-3",
      title: "Gamma",
      description: null,
      status: "in-progress",
      appetite: "large",
      deadline: "2026-04-12T12:00:00Z",
      created_at: "2026-04-02T09:00:00Z",
    });

    mocks.getProjects.mockImplementation((params: Record<string, unknown>) => {
      if (params.status === "completed") {
        return Promise.resolve(createPaginatedResponse([beta]));
      }
      if (params.appetite === "medium") {
        return Promise.resolve(createPaginatedResponse([beta]));
      }
      return Promise.resolve(createPaginatedResponse([alpha, beta, gamma]));
    });
    mocks.updateTask.mockResolvedValue({ id: "task-1", status: "done" });

    renderWithProviders(<ProjectsPage />);

    expect(await screen.findByRole("heading", { name: "Projects" })).toBeInTheDocument();
    expect(mocks.getProjects).toHaveBeenCalledWith({ limit: 50 });
    const projectButtons = await screen.findAllByRole("button", { name: /Open / });
    expect(projectButtons[0]).toHaveTextContent("Open Beta");
    expect(projectButtons[1]).toHaveTextContent("Open Gamma");
    expect(projectButtons[2]).toHaveTextContent("Open Alpha");

    const selects = screen.getAllByRole("combobox");
    fireEvent.change(selects[0], { target: { value: "completed" } });
    await waitFor(() => {
      expect(mocks.getProjects).toHaveBeenLastCalledWith({
        limit: 50,
        status: "completed",
      });
    });

    fireEvent.change(selects[1], { target: { value: "medium" } });
    await waitFor(() => {
      expect(mocks.getProjects).toHaveBeenLastCalledWith({
        appetite: "medium",
        limit: 50,
        status: "completed",
      });
    });

    fireEvent.change(selects[0], { target: { value: "all" } });
    fireEvent.change(selects[1], { target: { value: "all" } });
    fireEvent.change(selects[2], { target: { value: "title" } });
    await waitFor(() => {
      const reordered = screen.getAllByRole("button", { name: /Open / });
      expect(reordered[0]).toHaveTextContent("Open Alpha");
      expect(reordered[1]).toHaveTextContent("Open Beta");
      expect(reordered[2]).toHaveTextContent("Open Gamma");
    });

    fireEvent.change(selects[2], { target: { value: "created_at" } });
    await waitFor(() => {
      const reordered = screen.getAllByRole("button", { name: /Open / });
      expect(reordered[0]).toHaveTextContent("Open Beta");
      expect(reordered[1]).toHaveTextContent("Open Gamma");
      expect(reordered[2]).toHaveTextContent("Open Alpha");
    });

    fireEvent.click(screen.getByRole("button", { name: "Sort ascending" }));

    await waitFor(() => {
      const reordered = screen.getAllByRole("button", { name: /Open / });
      expect(reordered[0]).toHaveTextContent("Open Alpha");
      expect(reordered[1]).toHaveTextContent("Open Gamma");
      expect(reordered[2]).toHaveTextContent("Open Beta");
    });

    fireEvent.change(selects[2], { target: { value: "progress" } });
    await waitFor(() => {
      const reordered = screen.getAllByRole("button", { name: /Open / });
      expect(reordered[0]).toHaveTextContent("Open Gamma");
      expect(reordered[1]).toHaveTextContent("Open Beta");
      expect(reordered[2]).toHaveTextContent("Open Alpha");
    });

    fireEvent.click(screen.getByRole("button", { name: "Open Alpha" }));
    expect(await screen.findByText("Tree: Alpha")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Complete task-1" }));
    await waitFor(() => {
      expect(mocks.updateTask).toHaveBeenCalledWith("task-1", {
        status: "done",
      });
    });

    fireEvent.click(screen.getByRole("button", { name: "Back to all projects" }));
    expect(await screen.findByRole("button", { name: "Open Alpha" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Open Gamma" }));
    expect(await screen.findByText("Tree: Gamma")).toBeInTheDocument();
    expect(screen.queryByText("A shape-up style project")).not.toBeInTheDocument();
  });

  it("renders the loading state and resolves to the empty state", async () => {
    const pending = deferred<ReturnType<typeof createPaginatedResponse>>();
    mocks.getProjects.mockReturnValue(pending.promise);

    renderWithProviders(<ProjectsPage />);

    expect(screen.getAllByText("Skeleton")).toHaveLength(6);

    pending.resolve(createPaginatedResponse([]));

    expect(await screen.findByText("No projects yet")).toBeInTheDocument();
  });

  it("renders the empty state when no projects exist", async () => {
    mocks.getProjects.mockResolvedValue(createPaginatedResponse([]));

    renderWithProviders(<ProjectsPage />);

    expect(await screen.findByText("No projects yet")).toBeInTheDocument();
    expect(screen.getByText("Create or apply a draft to get started.")).toBeInTheDocument();
  });

  it("renders a specific page error and retries project loading", async () => {
    mocks.getProjects
      .mockRejectedValueOnce(new Error("Project service unavailable"))
      .mockResolvedValue(createPaginatedResponse([]));
    const user = userEvent.setup();

    renderWithProviders(<ProjectsPage />);

    expect(await screen.findByText("Page Error: Project service unavailable")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry projects" }));

    expect(await screen.findByText("No projects yet")).toBeInTheDocument();
    expect(mocks.getProjects).toHaveBeenCalledTimes(2);
  });

  it("falls back to a generic error for non-Error query failures", async () => {
    mocks.getProjects.mockRejectedValue("boom");

    renderWithProviders(<ProjectsPage />);

    expect(await screen.findByText("Page Error: Failed to load projects")).toBeInTheDocument();
  });

  it("creates a project from the complete modal form and opens its detail", async () => {
    const created = createProject({
      id: "project-created",
      title: "Public preview launch",
      description: "Prepare a safe source release",
      appetite: "medium",
      deadline: "2026-08-15T00:00:00",
    });
    mocks.getProjects.mockResolvedValue(createPaginatedResponse([]));
    mocks.createProject.mockResolvedValue(created);
    const user = userEvent.setup();

    renderWithProviders(<ProjectsPage />);

    expect(await screen.findByText("No projects yet")).toBeInTheDocument();
    const newProjectButtons = screen.getAllByRole("button", { name: "New Project" });
    await user.click(newProjectButtons[0]);

    expect(screen.getByRole("heading", { name: "New Project" })).toBeInTheDocument();
    const createButton = screen.getByRole("button", { name: "Create Project" });
    expect(createButton).toBeDisabled();

    await user.type(
      screen.getByPlaceholderText("e.g. Personal OS launch"),
      "  Public preview launch  ",
    );
    await user.type(
      screen.getByPlaceholderText("What does done look like?"),
      "  Prepare a safe source release  ",
    );
    await user.selectOptions(screen.getByRole("combobox", { name: "Appetite" }), "medium");
    fireEvent.change(screen.getByLabelText("Deadline"), {
      target: { value: "2026-08-15" },
    });
    await user.click(createButton);

    await waitFor(() => {
      expect(mocks.createProject).toHaveBeenCalledWith(
        {
          title: "Public preview launch",
          description: "Prepare a safe source release",
          appetite: "medium",
          deadline: "2026-08-15T00:00:00",
        },
        expect.anything(),
      );
    });
    expect(await screen.findByText("Tree: Public preview launch")).toBeInTheDocument();
    expect(mocks.toastSuccess).toHaveBeenCalledWith("Project created");
    expect(screen.queryByRole("heading", { name: "New Project" })).not.toBeInTheDocument();
  });

  it("resets and closes the create form from both dialog controls", async () => {
    mocks.getProjects.mockResolvedValue(createPaginatedResponse([]));
    const user = userEvent.setup();

    renderWithProviders(<ProjectsPage />);

    await screen.findByText("No projects yet");
    await user.click(screen.getAllByRole("button", { name: "New Project" })[0]);
    await user.type(screen.getByPlaceholderText("e.g. Personal OS launch"), "Temporary title");
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("heading", { name: "New Project" })).not.toBeInTheDocument();

    await user.click(screen.getAllByRole("button", { name: "New Project" })[0]);
    expect(screen.getByPlaceholderText("e.g. Personal OS launch")).toHaveValue("");
    await user.type(screen.getByPlaceholderText("e.g. Personal OS launch"), "Another title");
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("heading", { name: "New Project" })).not.toBeInTheDocument();

    await user.click(screen.getAllByRole("button", { name: "New Project" })[0]);
    await user.click(screen.getByRole("button", { name: "Close new project dialog" }));
    expect(screen.queryByRole("heading", { name: "New Project" })).not.toBeInTheDocument();
  });

  it("keeps the create form open and reports project creation errors", async () => {
    mocks.getProjects.mockResolvedValue(createPaginatedResponse([]));
    mocks.createProject.mockRejectedValue(new Error("Project creation failed"));
    const user = userEvent.setup();

    renderWithProviders(<ProjectsPage />);

    await screen.findByText("No projects yet");
    await user.click(screen.getAllByRole("button", { name: "New Project" })[0]);
    await user.type(screen.getByPlaceholderText("e.g. Personal OS launch"), "Risk register");
    await user.click(screen.getByRole("button", { name: "Create Project" }));

    await waitFor(() => {
      expect(mocks.toastError).toHaveBeenCalledWith("Project creation failed");
    });
    expect(screen.getByRole("heading", { name: "New Project" })).toBeInTheDocument();
  });

  it("renders draft details, disables applied drafts, and opens an applied project", async () => {
    const draft: ProjectDraft = {
      id: "draft-1",
      user_id: "owner",
      title: "Release hardening",
      source_message: "Plan the public release",
      status: "proposed",
      project_summary: "Close the remaining release gates.",
      total_estimated_hours: 12,
      milestone_count: 3,
      critical_path: ["Coverage", "Release audit"],
      risks: [],
      applied_project_id: null,
      breakdown: {},
      created_at: "2026-08-01T09:00:00Z",
      updated_at: "2026-08-01T09:00:00Z",
    };
    const appliedDraft: ProjectDraft = {
      ...draft,
      id: "draft-2",
      title: "Already applied",
      status: "applied",
      project_summary: null,
      total_estimated_hours: null,
      milestone_count: 0,
      critical_path: [],
      applied_project_id: "project-old",
    };
    const appliedProject = createProject({
      id: "project-from-draft",
      title: "Release hardening",
      description: "Close the remaining release gates.",
    });
    mocks.getProjects.mockResolvedValue(createPaginatedResponse([]));
    mocks.getProjectDrafts.mockResolvedValue(createPaginatedResponse([draft, appliedDraft]));
    mocks.applyProjectDraft.mockResolvedValue(appliedProject);
    const user = userEvent.setup();

    renderWithProviders(<ProjectsPage />);

    expect(await screen.findByText("Project Drafts")).toBeInTheDocument();
    expect(screen.getByText("3 milestones • 12h")).toBeInTheDocument();
    expect(screen.getByText("Critical path: Coverage, Release audit")).toBeInTheDocument();
    expect(screen.getByText("Close the remaining release gates.")).toBeInTheDocument();
    const applyButtons = screen.getAllByRole("button", { name: "Apply Draft" });
    expect(applyButtons[0]).toBeEnabled();
    expect(applyButtons[1]).toBeDisabled();

    await user.click(applyButtons[0]);

    await waitFor(() => {
      expect(mocks.applyProjectDraft).toHaveBeenCalledWith("draft-1");
    });
    expect(await screen.findByText("Tree: Release hardening")).toBeInTheDocument();
    expect(screen.queryByText("Project Drafts")).not.toBeInTheDocument();
  });
});

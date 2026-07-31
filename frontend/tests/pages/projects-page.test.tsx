import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, waitFor } from "@testing-library/react";
import { renderWithProviders, screen } from "../test-utils";
import { ProjectsPage } from "@/pages/projects";
import { createPaginatedResponse, createProject } from "../factories";
import type { Project, TaskStatus } from "@/types";

const mocks = vi.hoisted(() => ({
  createProject: vi.fn(),
  getProjects: vi.fn(),
  updateTask: vi.fn(),
}));

vi.mock("@/api/projects", () => ({
  createProject: mocks.createProject,
  getProjects: mocks.getProjects,
  updateTask: mocks.updateTask,
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
  PageError: ({ message }: { message: string }) => <div>Page Error: {message}</div>,
}));

vi.mock("@/components/ui/skeleton", () => ({
  Skeleton: () => <div>Skeleton</div>,
}));

vi.mock("@/components/ui/empty-state", () => ({
  EmptyState: ({ description, title }: { description?: string; title: string }) => (
    <div>
      <div>{title}</div>
      {description ? <div>{description}</div> : null}
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
      <button type="button" onClick={() => onTaskStatusChange?.("task-1", "completed")}>
        Complete task-1
      </button>
    </div>
  ),
}));

describe("ProjectsPage", () => {
  beforeEach(() => {
    mocks.createProject.mockReset();
    mocks.getProjects.mockReset();
    mocks.updateTask.mockReset();
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
    mocks.updateTask.mockResolvedValue({ id: "task-1", status: "completed" });

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
        status: "completed",
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
  });

  it("renders the page error when project loading fails", async () => {
    mocks.getProjects.mockRejectedValue("boom");

    renderWithProviders(<ProjectsPage />);

    expect(await screen.findByText("Page Error: Failed to load projects")).toBeInTheDocument();
  });
});

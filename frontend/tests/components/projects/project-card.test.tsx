import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen } from "../../test-utils";
import { ProjectCard } from "@/components/projects/project-card";
import { createEpic, createMilestone, createProject, createTask } from "../../factories";

describe("ProjectCard", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-04-07T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders planning projects with progress and due-soon metadata", () => {
    const onClick = vi.fn();

    renderWithProviders(
      <ProjectCard
        project={createProject({
          title: "Approval runtime",
          status: "planning",
          appetite: "small",
          deadline: "2026-04-09T12:00:00Z",
          epics: [
            createEpic({
              milestones: [
                createMilestone({
                  tasks: [
                    createTask({ id: "task-1", status: "completed" }),
                    createTask({ id: "task-2", status: "backlog", sort_order: 1 }),
                  ],
                }),
              ],
            }),
          ],
        })}
        onClick={onClick}
      />,
    );

    expect(screen.getByText("Planning")).toBeInTheDocument();
    expect(screen.getByText("1 wk")).toBeInTheDocument();
    expect(screen.getByText("Approval runtime")).toBeInTheDocument();
    expect(screen.getByText("50%")).toBeInTheDocument();
    expect(screen.getByText("1/2 tasks")).toBeInTheDocument();
    expect(screen.getByText("2d left!")).toBeInTheDocument();

    screen.getByText("Approval runtime").click();
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("renders fallback copy for projects without description or deadline", () => {
    renderWithProviders(
      <ProjectCard
        project={createProject({
          description: null,
          appetite: null,
          deadline: null,
        })}
      />,
    );

    expect(screen.getByText("No description")).toBeInTheDocument();
    expect(screen.getByText("No deadline")).toBeInTheDocument();
    expect(screen.getByText("0%")).toBeInTheDocument();
    expect(screen.getByText("0/0 tasks")).toBeInTheDocument();
  });

  it("renders completed and overdue states correctly", () => {
    const { rerender } = renderWithProviders(
      <ProjectCard
        project={createProject({
          status: "completed",
          deadline: "2026-04-01T12:00:00Z",
          epics: [
            createEpic({
              milestones: [
                createMilestone({
                  tasks: [createTask({ status: "completed" })],
                }),
              ],
            }),
          ],
        })}
      />,
    );

    expect(screen.getAllByText("Completed")).toHaveLength(2);
    expect(screen.getByText("100%")).toBeInTheDocument();

    rerender(
      <ProjectCard
        project={createProject({
          status: "in-progress",
          appetite: "large",
          deadline: "2026-04-06T12:00:00Z",
        })}
      />,
    );

    expect(screen.getByText("In Progress")).toBeInTheDocument();
    expect(screen.getByText("6 wk")).toBeInTheDocument();
    expect(screen.getByText("1d overdue")).toBeInTheDocument();
  });

  it("renders same-day, medium-range, and distant deadlines", () => {
    const { rerender } = renderWithProviders(
      <ProjectCard
        project={createProject({
          title: "Due today",
          deadline: "2026-04-07T12:00:00Z",
        })}
      />,
    );

    expect(screen.getByText("Due TODAY")).toBeInTheDocument();

    rerender(
      <ProjectCard
        project={createProject({
          title: "Due soon",
          deadline: "2026-04-13T12:00:00Z",
        })}
      />,
    );

    expect(screen.getByText("6d left")).toBeInTheDocument();

    rerender(
      <ProjectCard
        project={createProject({
          title: "Due later",
          deadline: "2026-04-17T12:00:00Z",
        })}
      />,
    );

    expect(screen.getByText("10d left")).toBeInTheDocument();
  });
});

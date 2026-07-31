import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent } from "../../test-utils";
import { TaskCard } from "@/components/projects/task-card";
import { createTask } from "../../factories";

describe("TaskCard", () => {
  it("renders task metadata, overflow tags, and cycles status when interactive", async () => {
    const user = userEvent.setup();
    const onStatusChange = vi.fn();

    renderWithProviders(
      <TaskCard
        task={createTask({
          title: "Implement approvals",
          status: "backlog",
          estimate_hours: 6,
          wsjf_score: 8.2,
          complexity: "high",
          context_tags: ["backend", "security", "workflow"],
        })}
        onStatusChange={onStatusChange}
      />,
    );

    expect(screen.getByText("Backlog")).toBeInTheDocument();
    expect(screen.getByText("Implement approvals")).toBeInTheDocument();
    expect(screen.getByText("6h")).toBeInTheDocument();
    expect(screen.getByText("8.2")).toBeInTheDocument();
    expect(screen.getByText("C")).toBeInTheDocument();
    expect(screen.getByText("backend")).toBeInTheDocument();
    expect(screen.getByText("security")).toBeInTheDocument();
    expect(screen.getByText("+1")).toBeInTheDocument();

    await user.click(screen.getByText("Backlog"));

    expect(onStatusChange).toHaveBeenCalledWith("task-1", "ready");
  });

  it("renders minimal tasks without optional metadata", () => {
    renderWithProviders(
      <TaskCard
        task={createTask({
          title: "Write summary",
          status: "completed",
        })}
      />,
    );

    expect(screen.getByText("Done")).toBeInTheDocument();
    expect(screen.getByText("Write summary")).toBeInTheDocument();
    expect(screen.getByText("--")).toBeInTheDocument();
    expect(screen.queryByText(/^\d+h$/)).not.toBeInTheDocument();
  });

  it.each([
    ["in-progress", "review"],
    ["blocked", "done"],
    ["completed", "backlog"],
  ])("cycles from %s to %s when clicked", async (status, nextStatus) => {
    const user = userEvent.setup();
    const onStatusChange = vi.fn();

    renderWithProviders(
      <TaskCard
        task={createTask({
          title: `Task ${status}`,
          status: status as "backlog" | "in-progress" | "blocked" | "completed",
        })}
        onStatusChange={onStatusChange}
      />,
    );

    await user.click(
      screen.getByText(
        status === "completed" ? "Done" : status === "blocked" ? "Blocked" : "In Progress",
      ),
    );

    expect(onStatusChange).toHaveBeenCalledWith("task-1", nextStatus);
  });

  it.each([
    [6.5, "text-[var(--color-warning-500)]", "font-semibold"],
    [4.5, "text-[var(--color-warning-900)]", undefined],
    [2.5, "text-[var(--color-info-500)]", undefined],
    [1.5, "text-[var(--color-info-900)]", undefined],
  ])("renders the expected WSJF styling for score %s", (score, colorClass, weightClass) => {
    renderWithProviders(
      <TaskCard
        task={createTask({
          title: `Score ${score}`,
          wsjf_score: score,
          complexity: "medium",
        })}
      />,
    );

    const wsjf = screen.getByText(score.toFixed(1));
    expect(wsjf).toHaveClass(colorClass);
    if (weightClass) {
      expect(wsjf).toHaveClass(weightClass);
    }
    expect(screen.getByText("M")).toBeInTheDocument();
  });

  it("renders the low-complexity badge when present", () => {
    renderWithProviders(
      <TaskCard
        task={createTask({
          title: "Low complexity task",
          complexity: "low",
        })}
      />,
    );

    expect(screen.getByText("S")).toBeInTheDocument();
  });
});

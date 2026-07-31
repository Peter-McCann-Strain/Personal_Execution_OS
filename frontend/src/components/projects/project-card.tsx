import { memo } from "react";
import { Calendar, CheckCircle2, Clock, ListTodo, Mountain, Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import { getProgressVariant } from "@/lib/colors";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type { Project, ProjectStatus, Appetite, Task } from "@/types";

// ─── Helpers ────────────────────────────────────────────────

function flattenTasks(project: Project): Task[] {
  return (project.epics ?? []).flatMap((epic) =>
    (epic.milestones ?? []).flatMap((milestone) => milestone.tasks ?? []),
  );
}

function isCompletedTask(status: string): boolean {
  return status === "done" || status === "completed";
}

function computeProgress(project: Project): {
  completed: number;
  total: number;
  percent: number;
} {
  const tasks = flattenTasks(project);
  const total = tasks.length;
  const completed = tasks.filter((t) => isCompletedTask(t.status)).length;
  const percent = total > 0 ? Math.round((completed / total) * 100) : 0;
  return { completed, total, percent };
}

function getDeadlineInfo(
  deadline: string | null,
  status: ProjectStatus,
): { text: string; className: string } {
  if (status === "completed") {
    return {
      text: "Completed",
      className: "text-[var(--color-success-500)]",
    };
  }
  if (!deadline) {
    return {
      text: "No deadline",
      className: "text-[var(--color-fg-tertiary)]",
    };
  }

  const now = new Date();
  const target = new Date(deadline);
  const diffMs = target.getTime() - now.getTime();
  const diffDays = Math.ceil(diffMs / (1000 * 60 * 60 * 24));

  if (diffDays < 0) {
    return {
      text: `${Math.abs(diffDays)}d overdue`,
      className:
        "text-[var(--color-error-900)] font-bold bg-[var(--color-error-50)] px-1.5 py-0.5 rounded-[var(--radius-sm)]",
    };
  }
  if (diffDays === 0) {
    return {
      text: "Due TODAY",
      className: "text-[var(--color-error-900)] font-bold",
    };
  }
  if (diffDays <= 3) {
    return {
      text: `${diffDays}d left!`,
      className: "text-[var(--color-warning-500)] font-bold",
    };
  }
  if (diffDays <= 7) {
    return {
      text: `${diffDays}d left`,
      className: "text-[var(--color-warning-500)] font-medium",
    };
  }
  return {
    text: `${diffDays}d left`,
    className: "text-[var(--color-fg-tertiary)]",
  };
}

// ─── Status Badge ───────────────────────────────────────────

const statusConfig: Record<
  ProjectStatus,
  { label: string; variant: "info" | "warning" | "success" | "default" }
> = {
  planning: { label: "Planning", variant: "info" },
  "in-progress": { label: "In Progress", variant: "warning" },
  completed: { label: "Completed", variant: "success" },
  cancelled: { label: "Cancelled", variant: "default" },
};

function StatusBadge({ status }: { status: ProjectStatus }) {
  const config = statusConfig[status] ?? { label: status, variant: "default" as const };
  return (
    <Badge variant={config.variant} size="sm">
      {config.label}
    </Badge>
  );
}

// ─── Appetite Badge ─────────────────────────────────────────

const appetiteConfig: Record<
  Appetite,
  { label: string; icon: React.ReactNode; className: string }
> = {
  small: {
    label: "1 wk",
    icon: <Zap className="h-3 w-3" />,
    className: "text-[var(--color-success-500)]",
  },
  medium: {
    label: "2 wk",
    icon: <Clock className="h-3 w-3" />,
    className: "text-[var(--color-warning-500)]",
  },
  large: {
    label: "6 wk",
    icon: <Mountain className="h-3 w-3" />,
    className: "text-[var(--color-error-900)]",
  },
};

function AppetiteBadge({ appetite }: { appetite: Appetite | null }) {
  if (!appetite) return null;
  const config = appetiteConfig[appetite];
  return (
    <span className={cn("inline-flex items-center gap-1 text-xs font-medium", config.className)}>
      {config.icon}
      {config.label}
    </span>
  );
}

// ─── Project Card ───────────────────────────────────────────

interface ProjectCardProps {
  project: Project;
  onClick?: () => void;
}

const ProjectCard = memo(function ProjectCard({ project, onClick }: ProjectCardProps) {
  const { completed, total, percent } = computeProgress(project);
  const deadline = getDeadlineInfo(project.deadline, project.status);

  return (
    <Card hoverable padding="none" className="group flex flex-col" onClick={onClick}>
      <div className="p-4">
        {/* Top row: status + appetite */}
        <div className="mb-3 flex items-center justify-between">
          <StatusBadge status={project.status} />
          <AppetiteBadge appetite={project.appetite} />
        </div>

        {/* Title */}
        <h3 className="mb-1 truncate text-sm font-semibold text-[var(--color-fg-primary)]">
          {project.title}
        </h3>

        {/* Description */}
        <p className="mb-3 line-clamp-2 text-xs text-[var(--color-fg-secondary)]">
          {project.description ?? "No description"}
        </p>

        {/* Progress bar */}
        <div className="mb-3 flex items-center gap-2">
          <Progress
            value={percent}
            colorVariant={getProgressVariant(percent)}
            className="h-1.5 flex-1"
          />
          <span className="min-w-[2.5rem] text-right text-xs font-medium font-mono text-[var(--color-fg-secondary)]">
            {percent === 100 ? (
              <span className="flex items-center gap-0.5 text-[var(--color-success-500)]">
                <CheckCircle2 className="h-3 w-3" />
                100%
              </span>
            ) : (
              `${percent}%`
            )}
          </span>
        </div>

        {/* Footer: tasks + deadline */}
        <div className="flex items-center justify-between text-xs text-[var(--color-fg-tertiary)]">
          <span className="inline-flex items-center gap-1">
            <ListTodo className="h-3 w-3" />
            {completed}/{total} tasks
          </span>
          <span className={cn("inline-flex items-center gap-1", deadline.className)}>
            <Calendar className="h-3 w-3" />
            {deadline.text}
          </span>
        </div>
      </div>
    </Card>
  );
});

export { ProjectCard, StatusBadge, AppetiteBadge };
export type { ProjectCardProps };

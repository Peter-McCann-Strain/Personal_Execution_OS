import { Ban, CheckCircle2, Circle, Loader2, Tag } from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import type { Task, TaskStatus, Complexity } from "@/types";

// ─── Status Config ──────────────────────────────────────────

const taskStatusConfig: Record<
  TaskStatus,
  {
    label: string;
    variant: "default" | "info" | "error" | "success" | "warning";
    icon: React.ReactNode;
  }
> = {
  backlog: {
    label: "Backlog",
    variant: "default",
    icon: <Circle className="h-3 w-3" />,
  },
  ready: {
    label: "Ready",
    variant: "warning",
    icon: <Circle className="h-3 w-3" />,
  },
  in_progress: {
    label: "In Progress",
    variant: "info",
    icon: <Loader2 className="h-3 w-3 animate-spin" />,
  },
  review: {
    label: "Review",
    variant: "warning",
    icon: <Loader2 className="h-3 w-3" />,
  },
  blocked: {
    label: "Blocked",
    variant: "error",
    icon: <Ban className="h-3 w-3" />,
  },
  done: {
    label: "Done",
    variant: "success",
    icon: <CheckCircle2 className="h-3 w-3" />,
  },
};

const STATUS_CYCLE: TaskStatus[] = ["backlog", "ready", "in_progress", "review", "blocked", "done"];

function normalizeTaskStatus(status: string): TaskStatus {
  switch (status) {
    case "in-progress":
      return "in_progress";
    case "completed":
      return "done";
    case "backlog":
    case "ready":
    case "in_progress":
    case "review":
    case "blocked":
    case "done":
      return status;
    default:
      return "backlog";
  }
}

// ─── Complexity Config ──────────────────────────────────────

const complexityConfig: Record<Complexity, { label: string; className: string }> = {
  low: {
    label: "S",
    className:
      "bg-[var(--color-success-50)] text-[var(--color-success-900)] border-[var(--color-success-500)]/30",
  },
  medium: {
    label: "M",
    className:
      "bg-[var(--color-warning-50)] text-[var(--color-warning-900)] border-[var(--color-warning-500)]/30",
  },
  high: {
    label: "C",
    className:
      "bg-[var(--color-error-50)] text-[var(--color-error-900)] border-[var(--color-error-500)]/30",
  },
};

// ─── WSJF Color ─────────────────────────────────────────────

function getWsjfColor(score: number | null): string {
  if (score == null) return "text-[var(--color-fg-tertiary)]";
  if (score >= 8) return "text-[var(--color-error-500)] font-bold";
  if (score >= 6) return "text-[var(--color-warning-500)] font-semibold";
  if (score >= 4) return "text-[var(--color-warning-900)]";
  if (score >= 2) return "text-[var(--color-info-500)]";
  return "text-[var(--color-info-900)]";
}

// ─── Task Status Badge ──────────────────────────────────────

interface TaskStatusBadgeProps {
  status: TaskStatus;
  onClick?: (nextStatus: TaskStatus) => void;
}

function TaskStatusBadge({ status, onClick }: TaskStatusBadgeProps) {
  const normalizedStatus = normalizeTaskStatus(status);
  const config = taskStatusConfig[normalizedStatus];

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!onClick) return;
    const currentIdx = STATUS_CYCLE.indexOf(normalizedStatus);
    const nextIdx = (currentIdx + 1) % STATUS_CYCLE.length;
    onClick(STATUS_CYCLE[nextIdx]);
  };

  return (
    <Badge
      variant={config.variant}
      size="sm"
      className={cn(onClick && "cursor-pointer hover:opacity-80")}
      onClick={handleClick}
    >
      <span className="inline-flex items-center gap-1">
        {config.icon}
        {config.label}
      </span>
    </Badge>
  );
}

// ─── Complexity Badge ───────────────────────────────────────

function ComplexityBadge({ complexity }: { complexity: Complexity | null }) {
  if (!complexity) return null;
  const config = complexityConfig[complexity];
  return (
    <span
      className={cn(
        "inline-flex h-5 w-5 items-center justify-center rounded-[var(--radius-sm)] border text-[10px] font-bold",
        config.className,
      )}
    >
      {config.label}
    </span>
  );
}

// ─── Task Card ──────────────────────────────────────────────

interface TaskCardProps {
  task: Task;
  onStatusChange?: (taskId: string, status: TaskStatus) => void;
}

function TaskCard({ task, onStatusChange }: TaskCardProps) {
  return (
    <div className="flex items-center gap-3 rounded-[var(--radius-md)] px-2 py-1.5 transition-colors hover:bg-[var(--color-bg-overlay)]">
      {/* Status */}
      <TaskStatusBadge
        status={normalizeTaskStatus(task.status)}
        onClick={onStatusChange ? (next) => onStatusChange(task.id, next) : undefined}
      />

      {/* Title */}
      <div className="flex-1 truncate">
        <div className="truncate text-sm text-[var(--color-fg-primary)]">{task.title}</div>
        {task.blocked_reason && (
          <div className="truncate text-xs text-[var(--color-fg-tertiary)]">
            {task.blocked_reason}
          </div>
        )}
      </div>

      {/* Estimate */}
      {task.estimate_hours != null && (
        <span className="text-xs text-[var(--color-fg-tertiary)]">{task.estimate_hours}h</span>
      )}

      {/* WSJF */}
      <span
        className={cn("min-w-[2.5rem] text-right font-mono text-xs", getWsjfColor(task.wsjf_score))}
      >
        {task.wsjf_score != null ? task.wsjf_score.toFixed(1) : "--"}
      </span>

      {/* Complexity */}
      <ComplexityBadge complexity={task.complexity} />

      {/* Context tags */}
      {task.context_tags.length > 0 && (
        <div className="hidden items-center gap-1 lg:flex">
          {task.context_tags.slice(0, 2).map((tag) => (
            <span
              key={tag}
              className="inline-flex items-center gap-0.5 rounded-[var(--radius-full)] bg-[var(--color-bg-overlay)] px-1.5 py-0.5 text-[10px] text-[var(--color-fg-tertiary)]"
            >
              <Tag className="h-2.5 w-2.5" />
              {tag}
            </span>
          ))}
          {task.context_tags.length > 2 && (
            <span className="text-[10px] text-[var(--color-fg-disabled)]">
              +{task.context_tags.length - 2}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

export { TaskCard, TaskStatusBadge, ComplexityBadge };
export type { TaskCardProps, TaskStatusBadgeProps };

import { useState, useCallback, useRef, useEffect } from "react";
import { Calendar, ChevronRight, FileText, Minus, Plus, Target } from "lucide-react";
import { cn, normalizeProgressFraction, normalizeProgressPercent } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { GoalStatusBadge, PriorityDot } from "@/components/goals/goal-tree";
import type { Goal, GoalStatus } from "@/types";

// ─── Goal Status Selector ───────────────────────────────────

const STATUS_OPTIONS: GoalStatus[] = ["active", "paused", "completed", "cancelled"];

interface GoalStatusSelectorProps {
  status: GoalStatus;
  onChange: (status: GoalStatus) => void;
}

function GoalStatusSelector({ status, onChange }: GoalStatusSelectorProps) {
  return (
    <div className="flex items-center gap-1.5">
      {STATUS_OPTIONS.map((s) => (
        <button
          key={s}
          type="button"
          onClick={() => onChange(s)}
          className={cn(
            "rounded-[var(--radius-full)] px-2.5 py-1 text-xs font-medium capitalize transition-colors",
            s === status
              ? "bg-[var(--color-info-500)] text-[var(--color-fg-on-accent)]"
              : "bg-[var(--color-bg-overlay)] text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-primary)]",
          )}
        >
          {s}
        </button>
      ))}
    </div>
  );
}

// ─── Progress Slider ────────────────────────────────────────

interface ProgressSliderProps {
  value: number;
  onChange: (value: number) => void;
}

function ProgressSlider({ value, onChange }: ProgressSliderProps) {
  const decrease = () => onChange(Math.max(0, value - 5));
  const increase = () => onChange(Math.min(100, value + 5));

  return (
    <div className="flex items-center gap-3">
      <Button
        variant="ghost"
        size="icon"
        onClick={decrease}
        className="h-7 w-7"
        aria-label="Decrease progress"
      >
        <Minus className="h-3 w-3" />
      </Button>

      <div className="flex flex-1 items-center gap-3">
        <input
          type="range"
          aria-label="Goal progress"
          min={0}
          max={100}
          step={1}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          className="h-2 w-full cursor-pointer appearance-none rounded-full bg-[var(--color-bg-overlay)] accent-[var(--color-info-500)]"
        />
        <span className="min-w-[3rem] text-right font-mono text-sm font-semibold text-[var(--color-fg-primary)]">
          {Math.round(value)}%
        </span>
      </div>

      <Button
        variant="ghost"
        size="icon"
        onClick={increase}
        className="h-7 w-7"
        aria-label="Increase progress"
      >
        <Plus className="h-3 w-3" />
      </Button>
    </div>
  );
}

// ─── Goal Detail Card ───────────────────────────────────────

interface GoalCardProps {
  goal: Goal;
  childGoals?: Goal[];
  onProgressChange?: (id: string, progress: number) => void;
  onStatusChange?: (id: string, status: GoalStatus) => void;
  onChildSelect?: (goal: Goal) => void;
}

function GoalCard({
  goal,
  childGoals = [],
  onProgressChange,
  onStatusChange,
  onChildSelect,
}: GoalCardProps) {
  const [localProgress, setLocalProgress] = useState(normalizeProgressPercent(goal.progress));
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Sync local progress when the goal prop changes (e.g., selecting a different goal)
  useEffect(() => {
    queueMicrotask(() => {
      setLocalProgress(normalizeProgressPercent(goal.progress));
    });
  }, [goal.progress]);

  // Clean up debounce timer on unmount
  useEffect(() => {
    return () => {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
      }
    };
  }, []);

  const handleProgressChange = useCallback(
    (value: number) => {
      setLocalProgress(value);

      // Debounce the API call so it only fires after the user stops dragging
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
      }
      debounceTimerRef.current = setTimeout(() => {
        onProgressChange?.(goal.id, normalizeProgressFraction(value));
      }, 400);
    },
    [goal.id, onProgressChange],
  );

  const handleStatusChange = useCallback(
    (status: GoalStatus) => {
      onStatusChange?.(goal.id, status);
    },
    [goal.id, onStatusChange],
  );

  const deadlineText = goal.deadline
    ? new Date(goal.deadline).toLocaleDateString("en-GB", {
        month: "long",
        day: "numeric",
        year: "numeric",
      })
    : "No deadline set";

  const [nowMs] = useState(Date.now);
  const daysLeft = goal.deadline
    ? Math.ceil((new Date(goal.deadline).getTime() - nowMs) / (1000 * 60 * 60 * 24))
    : null;

  return (
    <Card padding="lg" className="space-y-5">
      {/* Header */}
      <div>
        <div className="mb-2 flex items-center gap-2">
          <PriorityDot priority={goal.priority} />
          <GoalStatusBadge status={goal.status} />
          {goal.goal_type && (
            <Badge variant="default" size="sm" className="capitalize">
              {goal.goal_type}
            </Badge>
          )}
        </div>
        <h2 className="text-lg font-semibold text-[var(--color-fg-primary)]">{goal.title}</h2>
      </div>

      {/* Progress */}
      <div>
        <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-[var(--color-fg-tertiary)]">
          Progress
        </label>
        <Progress
          value={localProgress}
          colorVariant={
            localProgress >= 75
              ? "success"
              : localProgress >= 50
                ? "default"
                : localProgress >= 25
                  ? "warning"
                  : "error"
          }
          className="mb-2 h-2"
        />
        <ProgressSlider value={localProgress} onChange={handleProgressChange} />
      </div>

      {/* Status selector */}
      <div>
        <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-[var(--color-fg-tertiary)]">
          Status
        </label>
        <GoalStatusSelector status={goal.status} onChange={handleStatusChange} />
      </div>

      {/* Priority */}
      <div className="flex items-center gap-3">
        <span className="text-xs font-medium uppercase tracking-wider text-[var(--color-fg-tertiary)]">
          Priority
        </span>
        <div className="flex items-center gap-1.5">
          <PriorityDot priority={goal.priority} />
          <span className="font-mono text-sm font-medium text-[var(--color-fg-primary)]">
            {goal.priority}
          </span>
          <span className="text-xs text-[var(--color-fg-tertiary)]">/ 10</span>
        </div>
      </div>

      {/* Deadline */}
      <div className="flex items-center gap-2 text-sm text-[var(--color-fg-secondary)]">
        <Calendar className="h-4 w-4 text-[var(--color-fg-tertiary)]" />
        <span>{deadlineText}</span>
        {daysLeft != null && (
          <span
            className={cn(
              "font-mono text-xs",
              daysLeft < 0
                ? "text-[var(--color-error-900)] font-bold"
                : daysLeft <= 7
                  ? "text-[var(--color-warning-500)]"
                  : "text-[var(--color-fg-tertiary)]",
            )}
          >
            ({daysLeft < 0 ? `${Math.abs(daysLeft)}d overdue` : `${daysLeft}d left`})
          </span>
        )}
      </div>

      {/* Evidence */}
      {(goal.evidence ?? []).length > 0 && (
        <div>
          <label className="mb-1.5 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wider text-[var(--color-fg-tertiary)]">
            <FileText className="h-3 w-3" />
            Evidence ({goal.evidence.length})
          </label>
          <ul className="space-y-1.5">
            {goal.evidence.map((item, idx) => (
              <li
                key={idx}
                className="flex items-start gap-2 text-sm text-[var(--color-fg-secondary)]"
              >
                <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-[var(--color-fg-tertiary)]" />
                {item}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Child Goals */}
      {childGoals.length > 0 && (
        <div>
          <label className="mb-1.5 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wider text-[var(--color-fg-tertiary)]">
            <Target className="h-3 w-3" />
            Child Goals ({childGoals.length})
          </label>
          <div className="space-y-1.5">
            {childGoals.map((child) => (
              <ChildGoalButton
                key={child.id}
                goal={child}
                onSelect={() => onChildSelect?.(child)}
              />
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

function ChildGoalButton({ goal, onSelect }: { goal: Goal; onSelect: () => void }) {
  const progress = normalizeProgressPercent(goal.progress);

  return (
    <button
      type="button"
      onClick={onSelect}
      className="flex w-full items-center gap-2 rounded-[var(--radius-md)] bg-[var(--color-bg-elevated)] px-3 py-2 text-left transition-colors hover:bg-[var(--color-bg-overlay)]"
    >
      <PriorityDot priority={goal.priority} />
      <span className="flex-1 truncate text-sm text-[var(--color-fg-primary)]">{goal.title}</span>
      <Progress
        value={progress}
        className="h-1 w-12"
        colorVariant={progress >= 75 ? "success" : progress >= 50 ? "default" : "warning"}
      />
      <span className="font-mono text-xs text-[var(--color-fg-tertiary)]">
        {Math.round(progress)}%
      </span>
      <ChevronRight className="h-3 w-3 text-[var(--color-fg-disabled)]" />
    </button>
  );
}

export { GoalCard, GoalStatusSelector, ProgressSlider };
export type { GoalCardProps };

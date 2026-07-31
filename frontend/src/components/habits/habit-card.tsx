import { useMemo } from "react";
import { Check, Flame, Trophy, Hash, Clock } from "lucide-react";
import { isToday, parseISO } from "date-fns";
import { cn } from "@/lib/utils";
import { formatRelativeTime } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { Habit } from "@/api/habits";

// ─── Frequency Label ───────────────────────────────────────

function frequencyLabel(habit: Habit): string {
  if (habit.frequency === "custom" && habit.frequency_days != null) {
    return `Every ${habit.frequency_days}d`;
  }
  return habit.frequency.charAt(0).toUpperCase() + habit.frequency.slice(1);
}

function frequencyBadgeVariant(frequency: string): "default" | "info" | "warning" {
  switch (frequency) {
    case "daily":
      return "info";
    case "weekly":
      return "warning";
    default:
      return "default";
  }
}

// ─── Streak Health ─────────────────────────────────────────

function getStreakHealth(habit: Habit): {
  percent: number;
  variant: "success" | "warning" | "error" | "default";
} {
  if (habit.longest_streak === 0) {
    return { percent: 0, variant: "default" };
  }
  const ratio = habit.current_streak / Math.max(habit.longest_streak, 1);
  const percent = Math.min(Math.round(ratio * 100), 100);
  if (ratio >= 0.8) return { percent, variant: "success" };
  if (ratio >= 0.4) return { percent, variant: "warning" };
  return { percent, variant: "error" };
}

// ─── Completed Today Check ─────────────────────────────────

function isCompletedToday(lastCompletedAt: string | null): boolean {
  if (!lastCompletedAt) return false;
  return isToday(parseISO(lastCompletedAt));
}

// ─── Streak Color ──────────────────────────────────────────

const streakHealthColors: Record<string, string> = {
  success: "bg-[var(--color-success-500)]",
  warning: "bg-[var(--color-warning-500)]",
  error: "bg-[var(--color-error-500)]",
  default: "bg-[var(--color-bg-overlay)]",
};

// ─── Habit Card ────────────────────────────────────────────

interface HabitCardProps {
  habit: Habit;
  onComplete: (id: string) => void;
  onSelect: (habit: Habit) => void;
  isCompleting?: boolean;
}

function HabitCard({ habit, onComplete, onSelect, isCompleting }: HabitCardProps) {
  const completedToday = useMemo(
    () => isCompletedToday(habit.last_completed_at),
    [habit.last_completed_at],
  );

  const streakHealth = useMemo(() => getStreakHealth(habit), [habit]);

  const hasActiveStreak = habit.current_streak > 0;

  return (
    <Card
      hoverable
      padding="none"
      className="flex flex-col overflow-hidden"
      onClick={() => onSelect(habit)}
    >
      {/* Streak health bar */}
      <div className="h-1 w-full bg-[var(--color-bg-overlay)]">
        <div
          className={cn(
            "h-full transition-all duration-500 ease-out rounded-r-full",
            streakHealthColors[streakHealth.variant],
          )}
          style={{ width: `${streakHealth.percent}%` }}
        />
      </div>

      <div className="flex flex-col gap-3 p-4">
        {/* Header: name + frequency badge */}
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-sm font-semibold text-[var(--color-fg-primary)]">
              {habit.name}
            </h3>
            {habit.description && (
              <p className="mt-0.5 truncate text-xs text-[var(--color-fg-tertiary)]">
                {habit.description}
              </p>
            )}
          </div>
          <Badge variant={frequencyBadgeVariant(habit.frequency)} size="sm">
            {frequencyLabel(habit)}
          </Badge>
        </div>

        {/* Stats row */}
        <div className="flex items-center gap-4 text-xs">
          {/* Current streak */}
          <div
            className={cn(
              "flex items-center gap-1 font-medium",
              hasActiveStreak
                ? "text-[var(--color-warning-500)]"
                : "text-[var(--color-fg-tertiary)]",
            )}
          >
            <Flame className={cn("h-3.5 w-3.5", hasActiveStreak && "animate-pulse")} />
            <span>{habit.current_streak}</span>
          </div>

          {/* Longest streak */}
          <div className="flex items-center gap-1 text-[var(--color-fg-tertiary)]">
            <Trophy className="h-3.5 w-3.5" />
            <span>{habit.longest_streak}</span>
          </div>

          {/* Total completions */}
          <div className="flex items-center gap-1 text-[var(--color-fg-tertiary)]">
            <Hash className="h-3.5 w-3.5" />
            <span>{habit.total_completions}</span>
          </div>

          {/* Last completed */}
          {habit.last_completed_at && (
            <div className="ml-auto flex items-center gap-1 text-[var(--color-fg-tertiary)]">
              <Clock className="h-3 w-3" />
              <span>{formatRelativeTime(habit.last_completed_at)}</span>
            </div>
          )}
        </div>

        {/* Tags */}
        {habit.tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {habit.tags.map((tag) => (
              <Badge key={tag} variant="default" size="sm">
                {tag}
              </Badge>
            ))}
          </div>
        )}

        {/* Complete button */}
        <Button
          size="sm"
          variant={completedToday ? "outline" : "default"}
          disabled={completedToday || isCompleting}
          loading={isCompleting}
          className="w-full"
          onClick={(e) => {
            e.stopPropagation();
            onComplete(habit.id);
          }}
        >
          <Check className="h-4 w-4" />
          {completedToday ? "Done Today" : "Complete"}
        </Button>
      </div>
    </Card>
  );
}

export { HabitCard };
export type { HabitCardProps };

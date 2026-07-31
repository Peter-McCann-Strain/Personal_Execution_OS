import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Flame,
  Trophy,
  Hash,
  Calendar,
  Clock,
  Check,
  X,
  TrendingUp,
  MessageSquare,
} from "lucide-react";
import { format, parseISO, isToday, subDays, startOfDay, isSameDay } from "date-fns";
import { cn } from "@/lib/utils";
import { formatRelativeTime } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { getHabitLogs } from "@/api/habits";
import type { Habit, HabitLog } from "@/api/habits";

// ─── Completion Heatmap ────────────────────────────────────

interface HeatmapProps {
  logs: HabitLog[];
  days: number;
}

function CompletionHeatmap({ logs, days }: HeatmapProps) {
  const today = startOfDay(new Date());

  const completedDates = useMemo(() => {
    const set = new Set<string>();
    for (const log of logs) {
      set.add(format(parseISO(log.completed_at), "yyyy-MM-dd"));
    }
    return set;
  }, [logs]);

  const cells = useMemo(() => {
    const result: { date: Date; completed: boolean; isToday: boolean }[] = [];
    for (let i = days - 1; i >= 0; i--) {
      const date = subDays(today, i);
      const key = format(date, "yyyy-MM-dd");
      result.push({
        date,
        completed: completedDates.has(key),
        isToday: isSameDay(date, today),
      });
    }
    return result;
  }, [days, today, completedDates]);

  return (
    <div>
      <label className="mb-2 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wider text-[var(--color-fg-tertiary)]">
        <Calendar className="h-3 w-3" />
        Last {days} Days
      </label>
      <div className="flex flex-wrap gap-1">
        {cells.map((cell) => (
          <div
            key={format(cell.date, "yyyy-MM-dd")}
            title={`${format(cell.date, "MMM d")} — ${cell.completed ? "Completed" : "Missed"}`}
            className={cn(
              "h-4 w-4 rounded-[2px] transition-colors",
              cell.completed ? "bg-[var(--color-success-500)]" : "bg-[var(--color-bg-overlay)]",
              cell.isToday &&
                "ring-1 ring-[var(--color-border-strong)] ring-offset-1 ring-offset-[var(--color-bg-surface)]",
            )}
          />
        ))}
      </div>
      <div className="mt-2 flex items-center gap-3 text-[10px] text-[var(--color-fg-tertiary)]">
        <div className="flex items-center gap-1">
          <div className="h-3 w-3 rounded-[2px] bg-[var(--color-bg-overlay)]" />
          Missed
        </div>
        <div className="flex items-center gap-1">
          <div className="h-3 w-3 rounded-[2px] bg-[var(--color-success-500)]" />
          Completed
        </div>
      </div>
    </div>
  );
}

// ─── Stat Block ────────────────────────────────────────────

interface StatBlockProps {
  icon: React.ReactNode;
  label: string;
  value: string | number;
  highlight?: boolean;
}

function StatBlock({ icon, label, value, highlight }: StatBlockProps) {
  return (
    <div className="flex flex-col items-center gap-1 rounded-[var(--radius-md)] bg-[var(--color-bg-elevated)] px-3 py-2.5">
      <div
        className={cn(
          "flex items-center gap-1.5",
          highlight ? "text-[var(--color-warning-500)]" : "text-[var(--color-fg-tertiary)]",
        )}
      >
        {icon}
      </div>
      <span className="text-lg font-bold text-[var(--color-fg-primary)]">{value}</span>
      <span className="text-[10px] font-medium uppercase tracking-wider text-[var(--color-fg-tertiary)]">
        {label}
      </span>
    </div>
  );
}

// ─── Log Entry ─────────────────────────────────────────────

interface LogEntryProps {
  log: HabitLog;
}

function LogEntry({ log }: LogEntryProps) {
  const date = parseISO(log.completed_at);
  return (
    <div className="flex items-start gap-3 py-2">
      <div className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-[var(--color-success-500)]/20">
        <Check className="h-3 w-3 text-[var(--color-success-500)]" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-[var(--color-fg-primary)]">
            {format(date, "MMM d, yyyy")}
          </span>
          <span className="text-xs text-[var(--color-fg-tertiary)]">{format(date, "h:mm a")}</span>
        </div>
        {log.note && <p className="mt-0.5 text-xs text-[var(--color-fg-secondary)]">{log.note}</p>}
      </div>
    </div>
  );
}

// ─── Habit Detail ──────────────────────────────────────────

interface HabitDetailProps {
  habit: Habit;
  onComplete: (id: string, note?: string) => void;
  onClose: () => void;
  isCompleting?: boolean;
}

function HabitDetail({ habit, onComplete, onClose, isCompleting }: HabitDetailProps) {
  const [note, setNote] = useState("");

  const completedToday = useMemo(
    () => habit.last_completed_at != null && isToday(parseISO(habit.last_completed_at)),
    [habit.last_completed_at],
  );

  const { data: logs, isLoading: logsLoading } = useQuery({
    queryKey: ["habit-logs", habit.id],
    queryFn: () => getHabitLogs(habit.id, 30),
  });

  // Completion rate: completions in last 30 days / 30
  const completionRate = useMemo(() => {
    if (!logs) return null;
    const uniqueDays = new Set(logs.map((l) => format(parseISO(l.completed_at), "yyyy-MM-dd")));
    return Math.round((uniqueDays.size / 30) * 100);
  }, [logs]);

  const handleComplete = () => {
    onComplete(habit.id, note.trim() || undefined);
    setNote("");
  };

  return (
    <Card padding="lg" className="space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h2 className="text-lg font-semibold text-[var(--color-fg-primary)]">{habit.name}</h2>
          {habit.description && (
            <p className="mt-1 text-sm text-[var(--color-fg-secondary)]">{habit.description}</p>
          )}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-[var(--radius-md)] p-1.5 text-[var(--color-fg-tertiary)] transition-colors hover:bg-[var(--color-bg-overlay)] hover:text-[var(--color-fg-primary)]"
          aria-label="Close detail"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Tags + frequency */}
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="info" size="sm">
          {habit.frequency === "custom" && habit.frequency_days != null
            ? `Every ${habit.frequency_days} days`
            : habit.frequency}
        </Badge>
        {habit.tags.map((tag) => (
          <Badge key={tag} variant="default" size="sm">
            {tag}
          </Badge>
        ))}
        {habit.last_completed_at && (
          <span className="ml-auto flex items-center gap-1 text-xs text-[var(--color-fg-tertiary)]">
            <Clock className="h-3 w-3" />
            Last: {formatRelativeTime(habit.last_completed_at)}
          </span>
        )}
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <StatBlock
          icon={<Flame className="h-4 w-4" />}
          label="Current"
          value={habit.current_streak}
          highlight={habit.current_streak > 0}
        />
        <StatBlock
          icon={<Trophy className="h-4 w-4" />}
          label="Best"
          value={habit.longest_streak}
        />
        <StatBlock
          icon={<Hash className="h-4 w-4" />}
          label="Total"
          value={habit.total_completions}
        />
        <StatBlock
          icon={<TrendingUp className="h-4 w-4" />}
          label="Rate (30d)"
          value={completionRate != null ? `${completionRate}%` : "--"}
        />
      </div>

      {/* Heatmap */}
      {logsLoading ? (
        <Skeleton className="h-24 w-full" />
      ) : logs ? (
        <CompletionHeatmap logs={logs} days={30} />
      ) : null}

      {/* Complete with note */}
      <div>
        <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-[var(--color-fg-tertiary)]">
          Complete
        </label>
        <div className="flex items-center gap-2">
          <Input
            placeholder="Optional note..."
            value={note}
            onChange={(e) => setNote(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !completedToday) handleComplete();
            }}
            className="flex-1"
          />
          <Button
            size="md"
            variant={completedToday ? "outline" : "default"}
            disabled={completedToday || isCompleting}
            loading={isCompleting}
            onClick={handleComplete}
          >
            <Check className="h-4 w-4" />
            {completedToday ? "Done" : "Complete"}
          </Button>
        </div>
      </div>

      {/* Log history */}
      {logsLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      ) : logs && logs.length > 0 ? (
        <div>
          <label className="mb-1.5 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wider text-[var(--color-fg-tertiary)]">
            <MessageSquare className="h-3 w-3" />
            Recent Completions ({logs.length})
          </label>
          <div className="max-h-64 divide-y divide-[var(--color-border-subtle)] overflow-y-auto">
            {logs.map((log) => (
              <LogEntry key={log.id} log={log} />
            ))}
          </div>
        </div>
      ) : (
        <p className="py-4 text-center text-xs text-[var(--color-fg-tertiary)]">
          No completions in the last 30 days
        </p>
      )}
    </Card>
  );
}

export { HabitDetail };
export type { HabitDetailProps };

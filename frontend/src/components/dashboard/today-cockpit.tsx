import { useMemo } from "react";
import { useNavigate } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  AlertTriangle,
  ArrowRight,
  CalendarDays,
  CheckCircle2,
  Clock,
  Flame,
  ListChecks,
  Sparkles,
  Target,
} from "lucide-react";
import {
  differenceInCalendarDays,
  endOfDay,
  format,
  isToday,
  parseISO,
  startOfDay,
} from "date-fns";
import { getEvents } from "@/api/calendar";
import { getActiveGoals } from "@/api/dashboard";
import {
  getOpenCommitments,
  getOverdueCommitments,
  updateCommitmentStatus,
} from "@/api/commitments";
import { completeHabit, getHabits, type Habit } from "@/api/habits";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, normalizeProgressPercent, truncate } from "@/lib/utils";
import type { CalendarEvent, Commitment, Goal } from "@/types";

type NextAction =
  | {
      kind: "commitment";
      eyebrow: string;
      title: string;
      detail: string;
      tone: "urgent" | "default";
      commitment: Commitment;
    }
  | {
      kind: "event";
      eyebrow: string;
      title: string;
      detail: string;
      tone: "default";
      event: CalendarEvent;
    }
  | {
      kind: "habit";
      eyebrow: string;
      title: string;
      detail: string;
      tone: "default";
      habit: Habit;
    }
  | {
      kind: "goal";
      eyebrow: string;
      title: string;
      detail: string;
      tone: "default";
      goal: Goal;
    }
  | {
      kind: "capture";
      eyebrow: string;
      title: string;
      detail: string;
      tone: "default";
    };

function safeDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatTime(value: string): string {
  const date = safeDate(value);
  return date ? format(date, "HH:mm") : "--:--";
}

function formatDue(commitment: Commitment): string {
  const dueDate = safeDate(commitment.temporal_normalized);
  if (!dueDate) {
    return commitment.temporal_expression_raw ?? "No due date";
  }
  if (isToday(dueDate)) return "Due today";
  return format(dueDate, "EEE d MMM");
}

function commitmentTitle(commitment: Commitment): string {
  return commitment.normalized_action || commitment.verbatim_text;
}

function habitIntervalDays(habit: Habit): number {
  switch (habit.frequency) {
    case "daily":
      return 1;
    case "weekly":
      return 7;
    case "monthly":
      return 30;
    case "custom":
      return Math.max(1, habit.frequency_days ?? 1);
  }
}

function isHabitDueToday(habit: Habit): boolean {
  if (!habit.active) return false;
  if (!habit.last_completed_at) return true;

  const completedAt = parseISO(habit.last_completed_at);
  if (Number.isNaN(completedAt.getTime())) return true;
  if (isToday(completedAt)) return false;

  return differenceInCalendarDays(new Date(), completedAt) >= habitIntervalDays(habit);
}

function sortCommitments(commitments: Commitment[]): Commitment[] {
  return [...commitments].sort((a, b) => {
    const aDate = safeDate(a.temporal_normalized)?.getTime() ?? Number.MAX_SAFE_INTEGER;
    const bDate = safeDate(b.temporal_normalized)?.getTime() ?? Number.MAX_SAFE_INTEGER;
    return aDate - bDate;
  });
}

function uniqueCommitments(commitments: Commitment[]): Commitment[] {
  const seen = new Set<string>();
  const result: Commitment[] = [];
  for (const commitment of commitments) {
    if (seen.has(commitment.id)) continue;
    seen.add(commitment.id);
    result.push(commitment);
  }
  return result;
}

function buildNextAction({
  overdueCommitments,
  openCommitments,
  events,
  dueHabits,
  goals,
}: {
  overdueCommitments: Commitment[];
  openCommitments: Commitment[];
  events: CalendarEvent[];
  dueHabits: Habit[];
  goals: Goal[];
}): NextAction {
  const urgentCommitment = sortCommitments(overdueCommitments)[0];
  if (urgentCommitment) {
    return {
      kind: "commitment",
      eyebrow: "Overdue",
      title: commitmentTitle(urgentCommitment),
      detail: formatDue(urgentCommitment),
      tone: "urgent",
      commitment: urgentCommitment,
    };
  }

  const nextCommitment = sortCommitments(openCommitments)[0];
  if (
    nextCommitment?.temporal_normalized &&
    isToday(new Date(nextCommitment.temporal_normalized))
  ) {
    return {
      kind: "commitment",
      eyebrow: "Due today",
      title: commitmentTitle(nextCommitment),
      detail: formatDue(nextCommitment),
      tone: "default",
      commitment: nextCommitment,
    };
  }

  const now = Date.now();
  const nextEvent = events.find((event) => (safeDate(event.end)?.getTime() ?? 0) > now);
  if (nextEvent) {
    return {
      kind: "event",
      eyebrow: "Next event",
      title: nextEvent.summary,
      detail: `${formatTime(nextEvent.start)}-${formatTime(nextEvent.end)}`,
      tone: "default",
      event: nextEvent,
    };
  }

  const dueHabit = dueHabits[0];
  if (dueHabit) {
    return {
      kind: "habit",
      eyebrow: "Routine",
      title: dueHabit.name,
      detail: `${dueHabit.current_streak} day streak`,
      tone: "default",
      habit: dueHabit,
    };
  }

  const activeGoal = goals.find((goal) => normalizeProgressPercent(goal.progress) < 100);
  if (activeGoal) {
    return {
      kind: "goal",
      eyebrow: "Goal nudge",
      title: activeGoal.title,
      detail: `${Math.round(normalizeProgressPercent(activeGoal.progress))}% complete`,
      tone: "default",
      goal: activeGoal,
    };
  }

  return {
    kind: "capture",
    eyebrow: "Clear",
    title: "Capture the next thing on your mind",
    detail: "No urgent commitments, events, or due habits found.",
    tone: "default",
  };
}

function TodaySkeleton() {
  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-4">
      <Skeleton className="h-5 w-32" />
      <div className="mt-4 grid gap-4 lg:grid-cols-[1.2fr_1fr]">
        <Skeleton className="h-44 w-full" />
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-1">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      </div>
    </div>
  );
}

function CountPill({
  label,
  value,
  variant = "default",
}: {
  label: string;
  value: number;
  variant?: "default" | "urgent";
}) {
  return (
    <div
      className={cn(
        "rounded-[var(--radius-md)] border px-3 py-2",
        variant === "urgent"
          ? "border-[var(--color-error-500)]/40 bg-[var(--color-error-500)]/10"
          : "border-[var(--color-border-subtle)] bg-[var(--color-bg-elevated)]",
      )}
    >
      <div className="text-lg font-semibold tabular-nums text-[var(--color-fg-primary)]">
        {value}
      </div>
      <div className="text-[11px] text-[var(--color-fg-tertiary)]">{label}</div>
    </div>
  );
}

function EventRow({ event }: { event: CalendarEvent }) {
  const start = safeDate(event.start);
  const end = safeDate(event.end);
  const now = new Date();
  const active = start != null && end != null && start <= now && end >= now;

  return (
    <div className="flex items-center gap-3 rounded-[var(--radius-md)] px-2 py-2 hover:bg-[var(--color-bg-elevated)]">
      <span className="w-20 shrink-0 font-mono text-xs tabular-nums text-[var(--color-fg-secondary)]">
        {formatTime(event.start)}
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium text-[var(--color-fg-primary)]">
          {event.summary}
        </div>
        <div className="text-xs text-[var(--color-fg-tertiary)]">
          {formatTime(event.start)}-{formatTime(event.end)}
        </div>
      </div>
      {active ? (
        <Badge size="sm" variant="info">
          Now
        </Badge>
      ) : null}
    </div>
  );
}

function CommitmentRow({
  commitment,
  onComplete,
  busy,
}: {
  commitment: Commitment;
  onComplete: () => void;
  busy: boolean;
}) {
  return (
    <div className="rounded-[var(--radius-md)] px-2 py-2 hover:bg-[var(--color-bg-elevated)]">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-warning-500)]" />
        <div className="min-w-0 flex-1">
          <div className="line-clamp-2 text-sm font-medium text-[var(--color-fg-primary)]">
            {commitmentTitle(commitment)}
          </div>
          <div className="mt-0.5 text-xs text-[var(--color-fg-tertiary)]">
            {formatDue(commitment)}
          </div>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5 pl-7">
        <Button size="sm" variant="ghost" onClick={onComplete} loading={busy}>
          Done
        </Button>
      </div>
    </div>
  );
}

function HabitRow({
  habit,
  onComplete,
  busy,
}: {
  habit: Habit;
  onComplete: () => void;
  busy: boolean;
}) {
  return (
    <div className="rounded-[var(--radius-md)] px-2 py-2 hover:bg-[var(--color-bg-elevated)]">
      <div className="flex items-center gap-3">
        <Flame className="h-4 w-4 shrink-0 text-[var(--color-warning-500)]" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-[var(--color-fg-primary)]">
            {habit.name}
          </div>
          <div className="text-xs text-[var(--color-fg-tertiary)]">
            {habit.current_streak} day streak
          </div>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5 pl-7">
        <Button size="sm" variant="ghost" onClick={onComplete} loading={busy}>
          Complete
        </Button>
      </div>
    </div>
  );
}

export function TodayCockpit() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const todayRange = useMemo(() => {
    const today = new Date();
    return {
      key: format(today, "yyyy-MM-dd"),
      start: startOfDay(today).toISOString(),
      end: endOfDay(today).toISOString(),
    };
  }, []);

  const eventsQuery = useQuery({
    queryKey: ["dashboard", "today", "events", todayRange.key],
    queryFn: () => getEvents(todayRange.start, todayRange.end),
    staleTime: 30_000,
  });

  const openCommitmentsQuery = useQuery({
    queryKey: ["commitments", "open"],
    queryFn: () => getOpenCommitments(12),
    staleTime: 30_000,
  });

  const overdueCommitmentsQuery = useQuery({
    queryKey: ["commitments", "overdue"],
    queryFn: getOverdueCommitments,
    staleTime: 30_000,
  });

  const habitsQuery = useQuery({
    queryKey: ["habits"],
    queryFn: getHabits,
    staleTime: 30_000,
  });

  const goalsQuery = useQuery({
    queryKey: ["dashboardGoals", 4],
    queryFn: () => getActiveGoals(4),
    staleTime: 30_000,
  });

  const commitmentMutation = useMutation({
    mutationFn: (id: string) => updateCommitmentStatus(id, "completed"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["commitments"] });
      toast.success("Commitment marked complete");
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Failed to update commitment");
    },
  });

  const habitMutation = useMutation({
    mutationFn: (id: string) => completeHabit(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["habits"] });
      toast.success("Habit completed");
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Failed to complete habit");
    },
  });

  const events = useMemo(
    () =>
      [...(eventsQuery.data ?? [])].sort(
        (a, b) => new Date(a.start).getTime() - new Date(b.start).getTime(),
      ),
    [eventsQuery.data],
  );
  const overdueCommitments = overdueCommitmentsQuery.data ?? [];
  const openCommitments = sortCommitments(
    uniqueCommitments([
      ...(overdueCommitmentsQuery.data ?? []),
      ...(openCommitmentsQuery.data ?? []),
    ]),
  );
  const dueHabits = useMemo(
    () => (habitsQuery.data ?? []).filter(isHabitDueToday),
    [habitsQuery.data],
  );
  const goals = goalsQuery.data ?? [];

  const anyLoading =
    eventsQuery.isLoading ||
    openCommitmentsQuery.isLoading ||
    overdueCommitmentsQuery.isLoading ||
    habitsQuery.isLoading ||
    goalsQuery.isLoading;

  if (anyLoading) return <TodaySkeleton />;

  const nextAction = buildNextAction({
    overdueCommitments,
    openCommitments,
    events,
    dueHabits,
    goals,
  });
  const handleNextAction = () => {
    switch (nextAction.kind) {
      case "commitment":
        commitmentMutation.mutate(nextAction.commitment.id);
        break;
      case "habit":
        habitMutation.mutate(nextAction.habit.id);
        break;
      case "event":
        navigate("/calendar");
        break;
      case "goal":
        navigate("/goals");
        break;
      case "capture":
        navigate("/diary?capture=1");
        break;
    }
  };

  const nextActionLoading =
    (nextAction.kind === "commitment" && commitmentMutation.isPending) ||
    (nextAction.kind === "habit" && habitMutation.isPending);

  return (
    <section className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)]">
      <div className="flex flex-col gap-3 border-b border-[var(--color-border-subtle)] px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-[var(--color-info-500)]" />
            <h2 className="text-sm font-semibold text-[var(--color-fg-primary)]">Today</h2>
          </div>
          <p className="mt-1 text-xs text-[var(--color-fg-tertiary)]">
            {format(new Date(), "EEEE d MMMM")} - schedule, promises, routines, and next move.
          </p>
        </div>
        <div className="grid grid-cols-3 gap-2 sm:w-[360px]">
          <CountPill label="Events" value={events.length} />
          <CountPill label="Due habits" value={dueHabits.length} />
          <CountPill
            label="Overdue"
            value={overdueCommitments.length}
            variant={overdueCommitments.length > 0 ? "urgent" : "default"}
          />
        </div>
      </div>

      <div className="grid gap-0 lg:grid-cols-[1.1fr_1fr]">
        <div className="border-b border-[var(--color-border-subtle)] p-4 lg:border-b-0 lg:border-r">
          <div
            className={cn(
              "rounded-[var(--radius-lg)] border p-4",
              nextAction.tone === "urgent"
                ? "border-[var(--color-error-500)]/40 bg-[var(--color-error-500)]/10"
                : "border-[var(--color-border-subtle)] bg-[var(--color-bg-elevated)]",
            )}
          >
            <div className="mb-3 flex items-center justify-between gap-3">
              <Badge size="sm" variant={nextAction.tone === "urgent" ? "error" : "info"}>
                {nextAction.eyebrow}
              </Badge>
              <Clock className="h-4 w-4 text-[var(--color-fg-tertiary)]" />
            </div>
            <h3 className="max-w-2xl text-lg font-semibold leading-tight text-[var(--color-fg-primary)]">
              {truncate(nextAction.title, 110)}
            </h3>
            <p className="mt-2 text-sm text-[var(--color-fg-secondary)]">{nextAction.detail}</p>
            <div className="mt-4 flex flex-wrap gap-2">
              <Button onClick={handleNextAction} loading={nextActionLoading}>
                {nextAction.kind === "commitment" ? "Mark Done" : null}
                {nextAction.kind === "habit" ? "Complete Habit" : null}
                {nextAction.kind === "event" ? "Open Calendar" : null}
                {nextAction.kind === "goal" ? "Open Goals" : null}
                {nextAction.kind === "capture" ? "Quick Capture" : null}
                <ArrowRight className="h-4 w-4" />
              </Button>
              <Button
                variant="outline"
                onClick={() =>
                  navigate(
                    `/chat?prompt=${encodeURIComponent("Help me plan today from my schedule, commitments, habits, and goals.")}`,
                  )
                }
              >
                Ask Assistant
              </Button>
            </div>
          </div>
        </div>

        <div className="grid gap-0 md:grid-cols-3 lg:grid-cols-1">
          <div className="border-b border-[var(--color-border-subtle)] p-4 md:border-b-0 md:border-r lg:border-b lg:border-r-0">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-[var(--color-fg-tertiary)]">
                <CalendarDays className="h-4 w-4" />
                Schedule
              </h3>
              <button
                type="button"
                onClick={() => navigate("/calendar")}
                className="text-xs font-medium text-[var(--color-fg-secondary)] hover:text-[var(--color-fg-primary)]"
              >
                View
              </button>
            </div>
            {eventsQuery.isError ? (
              <p className="py-4 text-xs text-[var(--color-fg-tertiary)]">Calendar unavailable.</p>
            ) : events.length > 0 ? (
              <div className="space-y-0.5">
                {events.slice(0, 4).map((event) => (
                  <EventRow key={event.id} event={event} />
                ))}
              </div>
            ) : (
              <p className="py-4 text-xs text-[var(--color-fg-tertiary)]">No events today.</p>
            )}
          </div>

          <div className="border-b border-[var(--color-border-subtle)] p-4 md:border-b-0 md:border-r lg:border-b lg:border-r-0">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-[var(--color-fg-tertiary)]">
                <ListChecks className="h-4 w-4" />
                Commitments
              </h3>
              <button
                type="button"
                onClick={() => navigate("/commitments")}
                className="text-xs font-medium text-[var(--color-fg-secondary)] hover:text-[var(--color-fg-primary)]"
              >
                View
              </button>
            </div>
            {openCommitmentsQuery.isError || overdueCommitmentsQuery.isError ? (
              <p className="py-4 text-xs text-[var(--color-fg-tertiary)]">
                Commitments unavailable.
              </p>
            ) : openCommitments.length > 0 ? (
              <div className="space-y-0.5">
                {openCommitments.slice(0, 3).map((commitment) => (
                  <CommitmentRow
                    key={commitment.id}
                    commitment={commitment}
                    busy={commitmentMutation.isPending}
                    onComplete={() => commitmentMutation.mutate(commitment.id)}
                  />
                ))}
              </div>
            ) : (
              <p className="py-4 text-xs text-[var(--color-fg-tertiary)]">No open commitments.</p>
            )}
          </div>

          <div className="p-4">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-[var(--color-fg-tertiary)]">
                <Target className="h-4 w-4" />
                Routines
              </h3>
              <button
                type="button"
                onClick={() => navigate("/habits")}
                className="text-xs font-medium text-[var(--color-fg-secondary)] hover:text-[var(--color-fg-primary)]"
              >
                View
              </button>
            </div>
            {habitsQuery.isError ? (
              <p className="py-4 text-xs text-[var(--color-fg-tertiary)]">Habits unavailable.</p>
            ) : dueHabits.length > 0 ? (
              <div className="space-y-0.5">
                {dueHabits.slice(0, 3).map((habit) => (
                  <HabitRow
                    key={habit.id}
                    habit={habit}
                    busy={habitMutation.isPending}
                    onComplete={() => habitMutation.mutate(habit.id)}
                  />
                ))}
              </div>
            ) : (
              <div className="flex items-center gap-2 py-4 text-xs text-[var(--color-fg-tertiary)]">
                <CheckCircle2 className="h-4 w-4 text-[var(--color-success-500)]" />
                Routines are clear for today.
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

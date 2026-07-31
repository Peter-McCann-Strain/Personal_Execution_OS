import { useState, useMemo, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, Flame, CheckCircle2, Activity, Repeat } from "lucide-react";
import { isToday, parseISO } from "date-fns";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { PageError } from "@/components/ui/page-error";
import { PageHeader } from "@/components/ui/page-header";
import { PageTransition } from "@/components/ui/page-transition";
import { EmptyState } from "@/components/ui/empty-state";
import { HabitCard } from "@/components/habits/habit-card";
import { HabitDetail } from "@/components/habits/habit-detail";
import { CreateHabitModal } from "@/components/habits/create-habit-modal";
import { getHabits, createHabit, completeHabit } from "@/api/habits";
import type { Habit, CreateHabitData } from "@/api/habits";

// ─── Stats Summary ─────────────────────────────────────────

interface StatCardProps {
  icon: React.ReactNode;
  label: string;
  value: string | number;
}

function StatCard({ icon, label, value }: StatCardProps) {
  return (
    <div className="flex items-center gap-3 rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] px-4 py-3">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--color-bg-overlay)]">
        {icon}
      </div>
      <div>
        <p className="text-lg font-bold text-[var(--color-fg-primary)]">{value}</p>
        <p className="text-xs text-[var(--color-fg-tertiary)]">{label}</p>
      </div>
    </div>
  );
}

// ─── Habits Page ───────────────────────────────────────────

function HabitsPage() {
  const queryClient = useQueryClient();
  const [selectedHabit, setSelectedHabit] = useState<Habit | null>(null);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [completingId, setCompletingId] = useState<string | null>(null);

  // ── Fetch habits ──────────────────────────────────────────
  const {
    data: habits,
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ["habits"],
    queryFn: getHabits,
  });

  // ── Create habit mutation ─────────────────────────────────
  const createMutation = useMutation({
    mutationFn: createHabit,
    onSuccess: (newHabit) => {
      queryClient.invalidateQueries({ queryKey: ["habits"] });
      setCreateModalOpen(false);
      toast.success(`"${newHabit.name}" created`);
    },
    onError: (err) => {
      toast.error(err.message || "Failed to create habit");
    },
  });

  // ── Complete habit mutation ───────────────────────────────
  const completeMutation = useMutation({
    mutationFn: ({ id, note }: { id: string; note?: string }) => completeHabit(id, note),
    onMutate: ({ id }) => {
      setCompletingId(id);
    },
    onSuccess: (_log, { id }) => {
      queryClient.invalidateQueries({ queryKey: ["habits"] });
      queryClient.invalidateQueries({ queryKey: ["habit-logs", id] });
      toast.success("Habit completed!");
    },
    onError: (err) => {
      toast.error(err.message || "Failed to complete habit");
    },
    onSettled: () => {
      setCompletingId(null);
    },
  });

  // ── Handlers ──────────────────────────────────────────────

  const handleComplete = useCallback(
    (id: string, note?: string) => {
      completeMutation.mutate({ id, note });
    },
    [completeMutation],
  );

  const handleQuickComplete = useCallback(
    (id: string) => {
      completeMutation.mutate({ id });
    },
    [completeMutation],
  );

  const handleCreate = useCallback(
    (data: CreateHabitData) => {
      createMutation.mutate(data);
    },
    [createMutation],
  );

  const handleSelect = useCallback((habit: Habit) => {
    setSelectedHabit(habit);
  }, []);

  const handleCloseDetail = useCallback(() => {
    setSelectedHabit(null);
  }, []);

  // ── Computed stats ────────────────────────────────────────

  const activeHabits = useMemo(() => (habits ?? []).filter((h) => h.active), [habits]);

  const completionsToday = useMemo(
    () =>
      activeHabits.filter(
        (h) => h.last_completed_at != null && isToday(parseISO(h.last_completed_at)),
      ).length,
    [activeHabits],
  );

  const bestStreak = useMemo(
    () => activeHabits.reduce((max, h) => Math.max(max, h.current_streak), 0),
    [activeHabits],
  );

  // Keep selected habit in sync with latest data
  const effectiveSelected = useMemo(() => {
    if (!selectedHabit || !habits) return null;
    return habits.find((h) => h.id === selectedHabit.id) ?? null;
  }, [selectedHabit, habits]);

  return (
    <PageTransition>
      <div className="mx-auto max-w-6xl space-y-6 p-6">
        {/* Header */}
        <PageHeader title="Habits" subtitle="Build better routines, one day at a time" icon={Flame}>
          <Button size="sm" onClick={() => setCreateModalOpen(true)}>
            <Plus className="h-4 w-4" />
            New Habit
          </Button>
        </PageHeader>

        {/* Stats summary */}
        {!isLoading && !isError && activeHabits.length > 0 && (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <StatCard
              icon={<Activity className="h-4 w-4 text-[var(--color-info-500)]" />}
              label="Active Habits"
              value={activeHabits.length}
            />
            <StatCard
              icon={<CheckCircle2 className="h-4 w-4 text-[var(--color-success-500)]" />}
              label="Completed Today"
              value={`${completionsToday} / ${activeHabits.length}`}
            />
            <StatCard
              icon={<Flame className="h-4 w-4 text-[var(--color-warning-500)]" />}
              label="Best Active Streak"
              value={bestStreak}
            />
          </div>
        )}

        {/* Content */}
        {isLoading && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-48 w-full" />
            ))}
          </div>
        )}

        {isError && (
          <PageError
            message={error?.message ?? "Failed to load habits"}
            onRetry={() => refetch()}
            context="your habits"
            icon={Flame}
          />
        )}

        {!isLoading && !isError && activeHabits.length === 0 && (
          <EmptyState
            icon={Repeat}
            title="No habits yet"
            description="Build consistency by tracking your daily habits"
            action={{
              label: "Create Your First Habit",
              onClick: () => setCreateModalOpen(true),
            }}
          />
        )}

        {!isLoading && !isError && activeHabits.length > 0 && (
          <div className="grid gap-6 lg:grid-cols-[1fr_380px]">
            {/* Habit grid */}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              {activeHabits.map((habit) => (
                <HabitCard
                  key={habit.id}
                  habit={habit}
                  onComplete={handleQuickComplete}
                  onSelect={handleSelect}
                  isCompleting={completingId === habit.id}
                />
              ))}
            </div>

            {/* Detail panel */}
            {effectiveSelected ? (
              <div className="lg:sticky lg:top-6 lg:self-start">
                <HabitDetail
                  habit={effectiveSelected}
                  onComplete={handleComplete}
                  onClose={handleCloseDetail}
                  isCompleting={completingId === effectiveSelected.id}
                />
              </div>
            ) : (
              <div className="hidden rounded-[var(--radius-lg)] border border-dashed border-[var(--color-border-default)] p-8 text-center lg:block">
                <Repeat className="mx-auto mb-2 h-8 w-8 text-[var(--color-fg-disabled)]" />
                <p className="text-sm text-[var(--color-fg-tertiary)]">
                  Select a habit to view details
                </p>
              </div>
            )}
          </div>
        )}

        {/* Create modal */}
        <CreateHabitModal
          open={createModalOpen}
          onClose={() => setCreateModalOpen(false)}
          onCreate={handleCreate}
          isCreating={createMutation.isPending}
        />
      </div>
    </PageTransition>
  );
}

export { HabitsPage };

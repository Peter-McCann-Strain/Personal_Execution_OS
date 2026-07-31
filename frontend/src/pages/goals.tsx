import { useState, useMemo, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Target, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { PageError } from "@/components/ui/page-error";
import { PageHeader } from "@/components/ui/page-header";
import { PageTransition } from "@/components/ui/page-transition";
import { GoalTree } from "@/components/goals/goal-tree";
import { GoalCard } from "@/components/goals/goal-card";
import {
  createGoal,
  getGoals,
  updateGoalProgress,
  type CreateGoalData,
  type GoalQueryParams,
} from "@/api/goals";
import { FilterSelect } from "@/components/ui/filter-select";
import type { Goal, GoalStatus } from "@/types";

// ─── Filter Config ──────────────────────────────────────────

const STATUS_OPTIONS: { value: GoalStatus | "all"; label: string }[] = [
  { value: "all", label: "All Statuses" },
  { value: "active", label: "Active" },
  { value: "paused", label: "Paused" },
  { value: "completed", label: "Completed" },
  { value: "cancelled", label: "Cancelled" },
];

const TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: "all", label: "All Types" },
  { value: "life", label: "Life" },
  { value: "yearly", label: "Yearly" },
  { value: "quarterly", label: "Quarterly" },
  { value: "monthly", label: "Monthly" },
  { value: "weekly", label: "Weekly" },
];

function CreateGoalModal({
  open,
  onClose,
  onCreate,
  isCreating,
}: {
  open: boolean;
  onClose: () => void;
  onCreate: (data: CreateGoalData) => void;
  isCreating: boolean;
}) {
  const [title, setTitle] = useState("");
  const [goalType, setGoalType] = useState("life");
  const [priority, setPriority] = useState(5);
  const [deadline, setDeadline] = useState("");

  if (!open) return null;

  const resetAndClose = () => {
    setTitle("");
    setGoalType("life");
    setPriority(5);
    setDeadline("");
    onClose();
  };

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!title.trim()) return;
    const normalizedPriority = Math.min(10, Math.max(1, priority || 5));
    onCreate({
      title: title.trim(),
      goal_type: goalType,
      priority: normalizedPriority,
      deadline: deadline ? `${deadline}T00:00:00` : undefined,
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
      <button
        type="button"
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={resetAndClose}
        aria-label="Close new goal dialog"
      />
      <div className="relative z-10 w-full max-w-md rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] shadow-xl">
        <div className="flex items-center justify-between border-b border-[var(--color-border-subtle)] px-5 py-4">
          <h2 className="text-base font-semibold text-[var(--color-fg-primary)]">New Goal</h2>
          <button
            type="button"
            onClick={resetAndClose}
            className="rounded-[var(--radius-md)] p-1.5 text-[var(--color-fg-tertiary)] transition-colors hover:bg-[var(--color-bg-overlay)] hover:text-[var(--color-fg-primary)]"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4 px-5 py-4">
          <div>
            <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-[var(--color-fg-tertiary)]">
              Title <span className="text-[var(--color-error-500)]">*</span>
            </label>
            <Input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="e.g. Build a calm daily planning habit"
              autoFocus
              required
            />
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-[var(--color-fg-tertiary)]">
                Type
              </label>
              <select
                value={goalType}
                onChange={(event) => setGoalType(event.target.value)}
                className="h-9 w-full rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] px-3 text-sm text-[var(--color-fg-primary)]"
              >
                {TYPE_OPTIONS.filter((option) => option.value !== "all").map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-[var(--color-fg-tertiary)]">
                Priority
              </label>
              <Input
                type="number"
                min={1}
                max={10}
                value={priority}
                onChange={(event) => {
                  const nextPriority = Number(event.target.value);
                  setPriority(Number.isFinite(nextPriority) ? nextPriority : 5);
                }}
              />
            </div>
          </div>

          <div>
            <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-[var(--color-fg-tertiary)]">
              Deadline
            </label>
            <Input
              type="date"
              value={deadline}
              onChange={(event) => setDeadline(event.target.value)}
            />
          </div>

          <div className="flex justify-end gap-2 border-t border-[var(--color-border-subtle)] pt-4">
            <Button type="button" variant="ghost" onClick={resetAndClose}>
              Cancel
            </Button>
            <Button type="submit" loading={isCreating} disabled={!title.trim()}>
              Create Goal
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ─── Goals Page ─────────────────────────────────────────────

function GoalsPage() {
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<GoalStatus | "all">("all");
  const [typeFilter, setTypeFilter] = useState("all");
  const [selectedGoal, setSelectedGoal] = useState<Goal | null>(null);
  const [createModalOpen, setCreateModalOpen] = useState(false);

  const queryParams: GoalQueryParams = useMemo(() => {
    const params: GoalQueryParams = { limit: 100 };
    if (statusFilter !== "all") params.status = statusFilter;
    if (typeFilter !== "all") params.goal_type = typeFilter;
    return params;
  }, [statusFilter, typeFilter]);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["goals", queryParams],
    queryFn: () => getGoals(queryParams),
  });

  const progressMutation = useMutation({
    mutationFn: ({ id, progress }: { id: string; progress: number }) =>
      updateGoalProgress(id, progress),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["goals"] });
    },
  });

  const createGoalMutation = useMutation({
    mutationFn: createGoal,
    onSuccess: (goal) => {
      queryClient.invalidateQueries({ queryKey: ["goals"] });
      setSelectedGoal(goal);
      setCreateModalOpen(false);
      toast.success("Goal created");
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Failed to create goal");
    },
  });

  const goals = useMemo(() => data?.items ?? [], [data?.items]);

  // Auto-select first goal when data loads
  const firstGoal = goals[0] ?? null;
  const effectiveSelected = selectedGoal ?? firstGoal;

  const childGoals = useMemo(() => {
    if (!effectiveSelected) return [];
    return goals.filter((g) => g.parent_id === effectiveSelected.id);
  }, [goals, effectiveSelected]);

  const handleGoalSelect = useCallback((goal: Goal) => {
    setSelectedGoal(goal);
  }, []);

  const handleProgressChange = useCallback(
    (id: string, progress: number) => {
      progressMutation.mutate({ id, progress });
    },
    [progressMutation],
  );

  return (
    <PageTransition>
      <div className="mx-auto max-w-6xl space-y-6 p-6">
        {/* Header */}
        <PageHeader title="Goals" subtitle="Track what matters most" icon={Target}>
          <Button size="sm" onClick={() => setCreateModalOpen(true)}>
            <Plus className="h-4 w-4" />
            New Goal
          </Button>
        </PageHeader>

        {/* Filter bar */}
        <div className="flex flex-wrap items-center gap-3">
          <FilterSelect
            ariaLabel="Filter goals by status"
            value={statusFilter}
            options={STATUS_OPTIONS}
            onChange={setStatusFilter}
          />
          <FilterSelect
            ariaLabel="Filter goals by type"
            value={typeFilter}
            options={TYPE_OPTIONS}
            onChange={setTypeFilter}
          />
        </div>

        {/* Content */}
        {isLoading && (
          <div className="space-y-3">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        )}

        {isError && (
          <PageError
            message={error?.message ?? "Failed to load goals"}
            onRetry={() => refetch()}
            context="your goals"
            icon={Target}
          />
        )}

        {!isLoading && !isError && goals.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <Target className="mb-3 h-12 w-12 text-[var(--color-fg-disabled)]" />
            <h2 className="mb-1 text-lg font-medium text-[var(--color-fg-primary)]">
              No goals yet
            </h2>
            <p className="mb-4 text-sm text-[var(--color-fg-tertiary)]">
              Define your first goal to start tracking progress
            </p>
            <Button size="sm" onClick={() => setCreateModalOpen(true)}>
              <Plus className="h-4 w-4" />
              New Goal
            </Button>
          </div>
        )}

        {!isLoading && !isError && goals.length > 0 && (
          <div className="grid gap-6 lg:grid-cols-[1fr_380px]">
            {/* Tree view */}
            <div className="min-w-0">
              <GoalTree goals={goals} onSelect={handleGoalSelect} />
            </div>

            {/* Detail panel */}
            {effectiveSelected ? (
              <div className="lg:sticky lg:top-6 lg:self-start">
                <GoalCard
                  goal={effectiveSelected}
                  childGoals={childGoals}
                  onProgressChange={handleProgressChange}
                  onChildSelect={handleGoalSelect}
                />
              </div>
            ) : (
              <div className="hidden rounded-[var(--radius-lg)] border border-dashed border-[var(--color-border-default)] p-8 text-center lg:block">
                <Target className="mx-auto mb-2 h-8 w-8 text-[var(--color-fg-disabled)]" />
                <p className="text-sm text-[var(--color-fg-tertiary)]">
                  Select a goal to view details
                </p>
              </div>
            )}
          </div>
        )}
        <CreateGoalModal
          open={createModalOpen}
          onClose={() => setCreateModalOpen(false)}
          onCreate={(goal) => createGoalMutation.mutate(goal)}
          isCreating={createGoalMutation.isPending}
        />
      </div>
    </PageTransition>
  );
}

export { GoalsPage };

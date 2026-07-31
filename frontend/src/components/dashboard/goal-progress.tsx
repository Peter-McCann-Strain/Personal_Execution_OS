import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { Target } from "lucide-react";
import { getActiveGoals } from "@/api/dashboard";
import { cn, normalizeProgressPercent, truncate } from "@/lib/utils";
import { getProgressVariant } from "@/lib/colors";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import type { Goal } from "@/types";

function GoalItem({ goal }: { goal: Goal }) {
  const navigate = useNavigate();
  const pct = Math.round(normalizeProgressPercent(goal.progress));

  return (
    <button
      onClick={() => navigate("/goals")}
      className={cn(
        "flex flex-col gap-1.5 rounded-[var(--radius-md)] px-2 py-2 w-full text-left transition-colors",
        "hover:bg-[var(--color-bg-elevated)] cursor-pointer",
      )}
    >
      <div className="flex items-center justify-between">
        <span className="text-sm text-[var(--color-fg-primary)] truncate">
          {truncate(goal.title, 25)}
        </span>
        <span className="text-xs font-medium tabular-nums text-[var(--color-fg-secondary)] shrink-0 ml-2">
          {pct}%
        </span>
      </div>
      <Progress value={pct} colorVariant={getProgressVariant(pct)} className="h-1.5" />
    </button>
  );
}

export function GoalProgress() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["activeGoals"],
    queryFn: () => getActiveGoals(5),
    staleTime: 60_000,
  });

  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)]">
      <div className="flex items-center justify-between border-b border-[var(--color-border-subtle)] px-4 py-3">
        <h3 className="text-sm font-semibold text-[var(--color-fg-primary)]">Goal Progress</h3>
        <Target className="h-4 w-4 text-[var(--color-fg-tertiary)]" />
      </div>
      <div className="p-3">
        {isLoading && <GoalProgressSkeleton />}

        {isError && (
          <p className="text-xs text-[var(--color-fg-secondary)] px-2 py-4 text-center">
            Unable to load goals.
          </p>
        )}

        {data && data.length === 0 && (
          <p className="text-xs text-[var(--color-fg-tertiary)] px-2 py-4 text-center">
            No active goals. Set your first goal to track progress.
          </p>
        )}

        {data && data.length > 0 && (
          <div className="space-y-0.5">
            {data.map((goal: Goal) => (
              <GoalItem key={goal.id} goal={goal} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function GoalProgressSkeleton() {
  return (
    <div className="space-y-3 px-2">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="space-y-1.5">
          <div className="flex items-center justify-between">
            <Skeleton className="h-3.5 w-32" />
            <Skeleton className="h-3 w-8" />
          </div>
          <Skeleton className="h-1.5 w-full" />
        </div>
      ))}
    </div>
  );
}

export { GoalProgressSkeleton };

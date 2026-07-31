import { useQuery } from "@tanstack/react-query";
import { Activity } from "lucide-react";
import { getRecentAgentActivity } from "@/api/dashboard";
import { AgentBadge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { truncate } from "@/lib/utils";
import { formatActionTime } from "@/lib/date";
import type { AgentAction } from "@/types";

function ActivityItem({ action }: { action: AgentAction }) {
  return (
    <div className="flex items-start gap-3 px-2 py-2 hover:bg-[var(--color-bg-elevated)] rounded-[var(--radius-md)] transition-colors">
      <span className="text-xs font-mono tabular-nums text-[var(--color-fg-tertiary)] w-12 shrink-0 pt-0.5">
        {formatActionTime(action.created_at)}
      </span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <AgentBadge agent={action.agent_name} size="sm" />
        </div>
        <p className="text-sm text-[var(--color-fg-primary)] line-clamp-1">
          {action.output_summary ? truncate(action.output_summary, 50) : action.action_type}
        </p>
      </div>
    </div>
  );
}

export function RecentActivity() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["recentActivity"],
    queryFn: () => getRecentAgentActivity(5),
    staleTime: 30_000,
    refetchInterval: 30_000,
  });

  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)]">
      <div className="flex items-center justify-between border-b border-[var(--color-border-subtle)] px-4 py-3">
        <h3 className="text-sm font-semibold text-[var(--color-fg-primary)]">Agent Activity</h3>
        <Activity className="h-4 w-4 text-[var(--color-fg-tertiary)]" />
      </div>
      <div className="p-3">
        {isLoading && <RecentActivitySkeleton />}

        {isError && (
          <p className="text-xs text-[var(--color-fg-secondary)] px-2 py-4 text-center">
            Unable to load activity.
          </p>
        )}

        {data && data.length === 0 && (
          <p className="text-xs text-[var(--color-fg-tertiary)] px-2 py-4 text-center">
            No agent activity yet. Send a message to get started.
          </p>
        )}

        {data && data.length > 0 && (
          <div className="space-y-0.5">
            {data.map((action: AgentAction) => (
              <ActivityItem key={action.id} action={action} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function RecentActivitySkeleton() {
  return (
    <div className="space-y-3 px-2">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="flex items-start gap-3">
          <Skeleton className="h-3 w-12" />
          <div className="flex-1 space-y-1">
            <Skeleton className="h-4 w-16" />
            <Skeleton className="h-3.5 w-full" />
          </div>
        </div>
      ))}
    </div>
  );
}

export { RecentActivitySkeleton };

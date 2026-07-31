import { useState, useMemo, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Handshake, ListChecks } from "lucide-react";
import { toast } from "sonner";
import { Skeleton } from "@/components/ui/skeleton";
import { PageError } from "@/components/ui/page-error";
import { PageHeader } from "@/components/ui/page-header";
import { PageTransition } from "@/components/ui/page-transition";
import { EmptyState } from "@/components/ui/empty-state";
import { CommitmentCard } from "@/components/commitments/commitment-card";
import { CommitmentFilters, type CommitmentTab } from "@/components/commitments/commitment-filters";
import {
  getOpenCommitments,
  getOverdueCommitments,
  updateCommitmentStatus,
} from "@/api/commitments";
import type { Commitment, CommitmentStatus } from "@/types";

// ─── Date Grouping ──────────────────────────────────────────

interface CommitmentGroup {
  label: string;
  commitments: Commitment[];
}

function groupByDueDate(commitments: Commitment[]): CommitmentGroup[] {
  const groups: Record<string, Commitment[]> = {};
  const noDate: Commitment[] = [];

  for (const c of commitments) {
    if (c.temporal_normalized) {
      try {
        const dateKey = new Date(c.temporal_normalized).toLocaleDateString("en-GB", {
          weekday: "long",
          day: "numeric",
          month: "long",
          year: "numeric",
        });
        if (!groups[dateKey]) groups[dateKey] = [];
        groups[dateKey].push(c);
      } catch {
        noDate.push(c);
      }
    } else {
      noDate.push(c);
    }
  }

  // Sort date groups chronologically
  const sorted = Object.entries(groups).sort(([, a], [, b]) => {
    const aDate = a[0]?.temporal_normalized ?? "";
    const bDate = b[0]?.temporal_normalized ?? "";
    return aDate.localeCompare(bDate);
  });

  const result: CommitmentGroup[] = sorted.map(([label, items]) => ({
    label,
    commitments: items,
  }));

  if (noDate.length > 0) {
    result.push({ label: "No due date", commitments: noDate });
  }

  return result;
}

// ─── Status Change Toast Messages ───────────────────────────

const statusToastMessages: Record<CommitmentStatus, string> = {
  detected: "Commitment reset to detected",
  acknowledged: "Commitment acknowledged",
  completed: "Commitment marked as complete",
  cancelled: "Commitment cancelled",
};

// ─── CommitmentsPage Component ──────────────────────────────

function CommitmentsPage() {
  const queryClient = useQueryClient();

  // Filter state
  const [activeTab, setActiveTab] = useState<CommitmentTab>("open");
  const [selectedStatuses, setSelectedStatuses] = useState<CommitmentStatus[]>([]);

  // Fetch open commitments
  const openQuery = useQuery({
    queryKey: ["commitments", "open"],
    queryFn: () => getOpenCommitments(50),
  });

  // Fetch overdue commitments
  const overdueQuery = useQuery({
    queryKey: ["commitments", "overdue"],
    queryFn: () => getOverdueCommitments(),
  });

  const openCommitments = useMemo(() => openQuery.data ?? [], [openQuery.data]);
  const overdueCommitments = useMemo(() => overdueQuery.data ?? [], [overdueQuery.data]);
  const overdueCount = overdueCommitments.length;

  // Build "all" as the union of open + overdue (deduplicated)
  const allCommitments = useMemo(() => {
    const seen = new Set<string>();
    const result: Commitment[] = [];
    for (const c of [...overdueCommitments, ...openCommitments]) {
      if (!seen.has(c.id)) {
        seen.add(c.id);
        result.push(c);
      }
    }
    return result;
  }, [openCommitments, overdueCommitments]);

  // Select data based on active tab
  const baseCommitments = useMemo(() => {
    switch (activeTab) {
      case "open":
        return openCommitments;
      case "overdue":
        return overdueCommitments;
      case "all":
        return allCommitments;
    }
  }, [activeTab, openCommitments, overdueCommitments, allCommitments]);

  // Apply status filters
  const filteredCommitments = useMemo(() => {
    if (selectedStatuses.length === 0) return baseCommitments;
    return baseCommitments.filter((c) => selectedStatuses.includes(c.status));
  }, [baseCommitments, selectedStatuses]);

  // Group by due date
  const groupedCommitments = useMemo(
    () => groupByDueDate(filteredCommitments),
    [filteredCommitments],
  );

  // Status change mutation with optimistic updates
  const statusMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: CommitmentStatus }) =>
      updateCommitmentStatus(id, status),
    onMutate: async ({ id, status }) => {
      // Cancel outgoing refetches
      await queryClient.cancelQueries({ queryKey: ["commitments"] });

      // Snapshot previous state
      const previousOpen = queryClient.getQueryData<Commitment[]>(["commitments", "open"]);
      const previousOverdue = queryClient.getQueryData<Commitment[]>(["commitments", "overdue"]);

      // Optimistic update helper
      const updateList = (list: Commitment[] | undefined) =>
        list?.map((c) =>
          c.id === id ? { ...c, status, updated_at: new Date().toISOString() } : c,
        );

      queryClient.setQueryData(["commitments", "open"], updateList(previousOpen));
      queryClient.setQueryData(["commitments", "overdue"], updateList(previousOverdue));

      return { previousOpen, previousOverdue };
    },
    onError: (_err, _vars, context) => {
      // Rollback on error
      if (context?.previousOpen) {
        queryClient.setQueryData(["commitments", "open"], context.previousOpen);
      }
      if (context?.previousOverdue) {
        queryClient.setQueryData(["commitments", "overdue"], context.previousOverdue);
      }
      toast.error("Failed to update commitment status");
    },
    onSuccess: (_data, { status }) => {
      toast.success(statusToastMessages[status]);
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["commitments"] });
    },
  });

  // Handlers
  const handleStatusChange = useCallback(
    (id: string, status: CommitmentStatus) => {
      statusMutation.mutate({ id, status });
    },
    [statusMutation],
  );

  const handleStatusToggle = useCallback((status: CommitmentStatus) => {
    setSelectedStatuses((prev) =>
      prev.includes(status) ? prev.filter((s) => s !== status) : [...prev, status],
    );
  }, []);

  // Loading / error states
  const isLoading = openQuery.isLoading || overdueQuery.isLoading;
  const isError = openQuery.isError || overdueQuery.isError;
  const errorMessage =
    openQuery.error?.message ?? overdueQuery.error?.message ?? "Failed to load commitments";
  const refetch = () => {
    openQuery.refetch();
    overdueQuery.refetch();
  };

  return (
    <PageTransition>
      <div className="mx-auto flex max-w-4xl flex-col gap-6 p-6">
        {/* Header */}
        <PageHeader
          title="Commitments"
          subtitle="Track promises and follow-ups"
          icon={ListChecks}
          agentColor="notification"
        >
          {overdueCount > 0 && (
            <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-[var(--color-error-500)] px-1.5 text-[10px] font-bold text-white">
              {overdueCount}
            </span>
          )}
        </PageHeader>

        {/* Filters */}
        <CommitmentFilters
          activeTab={activeTab}
          onTabChange={setActiveTab}
          selectedStatuses={selectedStatuses}
          onStatusToggle={handleStatusToggle}
          overdueCount={overdueCount}
        />

        {/* Content */}
        {isError && (
          <PageError
            message={errorMessage}
            onRetry={refetch}
            context="your commitments"
            icon={ListChecks}
          />
        )}

        {isLoading && (
          <div className="flex flex-col gap-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-32 w-full" />
            ))}
          </div>
        )}

        {!isLoading && !isError && filteredCommitments.length === 0 && (
          <EmptyState
            icon={Handshake}
            title="No commitments tracked yet"
            description="Commitments are promises and reminders extracted from your conversations. They will appear here automatically."
          />
        )}

        {!isLoading && !isError && filteredCommitments.length > 0 && (
          <div className="flex flex-col gap-6">
            {groupedCommitments.map((group) => (
              <div key={group.label} className="flex flex-col gap-3">
                {/* Group header */}
                <div className="flex items-center gap-2">
                  <div className="h-px flex-1 bg-[var(--color-border-subtle)]" />
                  <span className="text-xs font-semibold uppercase tracking-wider text-[var(--color-fg-tertiary)]">
                    {group.label} <span className="font-normal">({group.commitments.length})</span>
                  </span>
                  <div className="h-px flex-1 bg-[var(--color-border-subtle)]" />
                </div>

                {/* Commitment cards */}
                {group.commitments.map((commitment) => (
                  <CommitmentCard
                    key={commitment.id}
                    commitment={commitment}
                    onStatusChange={handleStatusChange}
                    isPending={
                      statusMutation.isPending && statusMutation.variables?.id === commitment.id
                    }
                  />
                ))}
              </div>
            ))}
          </div>
        )}
      </div>
    </PageTransition>
  );
}

export { CommitmentsPage };

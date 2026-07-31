import { useState, useMemo, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Plus, Scale } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { PageError } from "@/components/ui/page-error";
import { PageHeader } from "@/components/ui/page-header";
import { PageTransition } from "@/components/ui/page-transition";
import { DecisionCard } from "@/components/decisions/decision-card";
import { DecisionDetail } from "@/components/decisions/decision-detail";
import { CreateDecisionModal } from "@/components/decisions/create-decision-modal";
import {
  getDecisions,
  getDecisionsDueReview,
  type Decision,
  type DecisionStatus,
  type DecisionQueryParams,
} from "@/api/decisions";

// ─── Filter Config ─────────────────────────────────────────

type FilterTab = "all" | DecisionStatus;

const FILTER_OPTIONS: { value: FilterTab; label: string }[] = [
  { value: "all", label: "All" },
  { value: "pending_review", label: "Pending Review" },
  { value: "reviewed", label: "Reviewed" },
  { value: "archived", label: "Archived" },
];

const PAGE_SIZE = 25;

// ─── Decisions Page ────────────────────────────────────────

function DecisionsPage() {
  const [filter, setFilter] = useState<FilterTab>("all");
  const [offset, setOffset] = useState(0);
  const [selectedDecision, setSelectedDecision] = useState<Decision | null>(null);
  const [createModalOpen, setCreateModalOpen] = useState(false);

  // Reset offset when filter changes
  const handleFilterChange = useCallback((newFilter: FilterTab) => {
    setFilter(newFilter);
    setOffset(0);
  }, []);

  // ─── Queries ─────────────────────────────────────────────

  const queryParams: DecisionQueryParams = useMemo(() => {
    const params: DecisionQueryParams = {
      limit: PAGE_SIZE,
      offset,
    };
    if (filter !== "all") params.status = filter;
    return params;
  }, [filter, offset]);

  const {
    data: decisionsData,
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ["decisions", queryParams],
    queryFn: () => getDecisions(queryParams),
  });

  const { data: dueReview } = useQuery({
    queryKey: ["decisions-due-review"],
    queryFn: getDecisionsDueReview,
  });

  const decisions = decisionsData?.items ?? [];
  const hasMore = decisionsData?.has_more ?? false;
  const total = decisionsData?.total ?? 0;
  const dueCount = dueReview?.length ?? 0;

  // ─── Handlers ────────────────────────────────────────────

  const handleSelectDecision = useCallback((decision: Decision) => {
    setSelectedDecision(decision);
  }, []);

  const handleLoadMore = useCallback(() => {
    setOffset((prev) => prev + PAGE_SIZE);
  }, []);

  const handleReviewNow = useCallback(() => {
    setFilter("pending_review");
    setOffset(0);
    setSelectedDecision(null);
  }, []);

  // ─── Detail View ─────────────────────────────────────────

  if (selectedDecision) {
    return <DecisionDetail decision={selectedDecision} onBack={() => setSelectedDecision(null)} />;
  }

  // ─── List View ───────────────────────────────────────────

  return (
    <PageTransition>
      <div className="mx-auto max-w-3xl space-y-6 p-6">
        {/* Header */}
        <PageHeader title="Decision Journal" subtitle="Record and review your choices" icon={Scale}>
          <Button size="sm" onClick={() => setCreateModalOpen(true)}>
            <Plus className="h-4 w-4" />
            New Decision
          </Button>
        </PageHeader>

        {/* Due for review alert */}
        {dueCount > 0 && filter !== "pending_review" && (
          <div className="flex items-center gap-3 rounded-[var(--radius-lg)] border border-[var(--color-warning-500)]/30 bg-[var(--color-warning-50)] px-4 py-3">
            <AlertTriangle className="h-5 w-5 shrink-0 text-[var(--color-warning-500)]" />
            <div className="flex-1">
              <p className="text-sm font-medium text-[var(--color-warning-900)]">
                {dueCount} decision{dueCount !== 1 ? "s" : ""} due for review
              </p>
              <p className="text-xs text-[var(--color-warning-900)]/70">
                Record outcomes to learn from past decisions
              </p>
            </div>
            <button
              type="button"
              onClick={handleReviewNow}
              className="text-sm font-medium text-[var(--color-warning-900)] underline hover:no-underline"
            >
              Review Now
            </button>
          </div>
        )}

        {/* Filter tabs */}
        <div className="flex items-center gap-2" role="tablist" aria-label="Decision status filter">
          {FILTER_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => handleFilterChange(opt.value)}
              role="tab"
              aria-selected={filter === opt.value}
              tabIndex={filter === opt.value ? 0 : -1}
              className={cn(
                "rounded-[var(--radius-full)] px-3 py-1 text-xs font-medium transition-colors",
                filter === opt.value
                  ? "bg-[var(--color-info-500)] text-[var(--color-fg-on-accent)]"
                  : "bg-[var(--color-bg-overlay)] text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-primary)]",
              )}
            >
              {opt.label}
            </button>
          ))}
          {total > 0 && (
            <span className="ml-auto text-xs text-[var(--color-fg-tertiary)]">
              {total} decision{total !== 1 ? "s" : ""}
            </span>
          )}
        </div>

        {/* Loading */}
        {isLoading && (
          <div className="space-y-4">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-36 w-full" />
            ))}
          </div>
        )}

        {/* Error */}
        {isError && (
          <PageError
            message={error?.message ?? "Failed to load decisions"}
            onRetry={() => refetch()}
            context="your decisions"
            icon={Scale}
          />
        )}

        {/* Empty state */}
        {!isLoading && !isError && decisions.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <Scale className="mb-3 h-12 w-12 text-[var(--color-fg-disabled)]" />
            <h2 className="mb-1 text-lg font-medium text-[var(--color-fg-primary)]">
              {filter === "all" ? "No decisions yet" : `No ${filter.replace("_", " ")} decisions`}
            </h2>
            <p className="mb-4 text-sm text-[var(--color-fg-tertiary)]">
              {filter === "all"
                ? "Record your first decision to start building your decision journal"
                : "Decisions matching this filter will appear here"}
            </p>
            {filter === "all" && (
              <Button size="sm" onClick={() => setCreateModalOpen(true)}>
                <Plus className="h-4 w-4" />
                New Decision
              </Button>
            )}
          </div>
        )}

        {/* Decision cards */}
        {!isLoading && !isError && decisions.length > 0 && (
          <div className="space-y-4">
            {decisions.map((decision) => (
              <DecisionCard
                key={decision.id}
                decision={decision}
                onClick={() => handleSelectDecision(decision)}
              />
            ))}

            {/* Load more */}
            {hasMore && (
              <div className="flex justify-center pt-4">
                <Button variant="outline" size="sm" onClick={handleLoadMore}>
                  Load More
                </Button>
              </div>
            )}
          </div>
        )}

        {/* Create Decision Modal */}
        <CreateDecisionModal open={createModalOpen} onOpenChange={setCreateModalOpen} />
      </div>
    </PageTransition>
  );
}

export { DecisionsPage };

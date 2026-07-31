import { useState, useMemo, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, GraduationCap, BookOpen } from "lucide-react";
import { toast } from "sonner";
import { Skeleton } from "@/components/ui/skeleton";
import { PageError } from "@/components/ui/page-error";
import { PageHeader } from "@/components/ui/page-header";
import { PageTransition } from "@/components/ui/page-transition";
import { EmptyState } from "@/components/ui/empty-state";
import { Pagination } from "@/components/ui/pagination";
import { TutorialCard } from "@/components/tutorials/tutorial-card";
import { TutorialSession } from "@/components/tutorials/tutorial-session";
import { TutorialDetailView } from "@/components/tutorials/tutorial-detail";
import {
  getTutorials,
  getTutorial,
  startTutorial,
  type Tutorial,
  type TutorialQueryParams,
} from "@/api/tutorials";

// ─── Constants ──────────────────────────────────────────────

const PAGE_SIZE = 10;

type ViewMode = "list" | "session" | "detail";

// ─── Phase Filter ───────────────────────────────────────────

const PHASE_OPTIONS: {
  value: "all" | "submitted" | "dialogue" | "complete";
  label: string;
}[] = [
  { value: "all", label: "All" },
  { value: "dialogue", label: "Active" },
  { value: "complete", label: "Completed" },
  { value: "submitted", label: "Submitted" },
];

// ─── Tutorials Page ─────────────────────────────────────────

function TutorialsPage() {
  const queryClient = useQueryClient();

  // View state
  const [viewMode, setViewMode] = useState<ViewMode>("list");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [phaseFilter, setPhaseFilter] = useState<"all" | "submitted" | "dialogue" | "complete">(
    "all",
  );
  const [page, setPage] = useState(1);

  // ─── List Query ───────────────────────────────────────────
  const queryParams: TutorialQueryParams = useMemo(
    () => ({
      limit: PAGE_SIZE,
      offset: (page - 1) * PAGE_SIZE,
    }),
    [page],
  );

  const {
    data: listData,
    isLoading: listLoading,
    isError: listError,
    error: listErr,
    refetch: refetchList,
  } = useQuery({
    queryKey: ["tutorials", queryParams],
    queryFn: () => getTutorials(queryParams),
  });

  // ─── Detail Query ─────────────────────────────────────────
  const {
    data: detailData,
    isLoading: detailLoading,
    isError: detailError,
    error: detailErr,
  } = useQuery({
    queryKey: ["tutorials", selectedId],
    queryFn: () => getTutorial(selectedId!),
    enabled: !!selectedId && viewMode !== "list",
  });

  // ─── Start Tutorial Mutation ──────────────────────────────
  const startMutation = useMutation({
    mutationFn: (id: string) => startTutorial(id),
    onSuccess: (_response, id) => {
      queryClient.invalidateQueries({ queryKey: ["tutorials"] });
      // Refetch detail and go to session
      setSelectedId(id);
      setViewMode("session");
      queryClient.invalidateQueries({ queryKey: ["tutorials", id] });
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to start tutorial");
    },
  });

  // ─── Filtered Tutorials ───────────────────────────────────
  const tutorials = useMemo(() => {
    const items = listData?.items ?? [];
    if (phaseFilter === "all") return items;
    return items.filter((t) => t.phase === phaseFilter);
  }, [listData, phaseFilter]);

  const totalPages = listData ? Math.ceil(listData.total / PAGE_SIZE) : 0;

  // ─── Handlers ─────────────────────────────────────────────
  const handleSelectTutorial = useCallback(
    (tutorial: Tutorial) => {
      setSelectedId(tutorial.id);
      if (tutorial.phase === "dialogue") {
        setViewMode("session");
      } else if (tutorial.phase === "submitted") {
        // Start it
        startMutation.mutate(tutorial.id);
      } else {
        setViewMode("detail");
      }
    },
    [startMutation],
  );

  const handleBack = useCallback(() => {
    setViewMode("list");
    setSelectedId(null);
  }, []);

  const handleSessionComplete = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["tutorials"] });
    if (selectedId) {
      queryClient.invalidateQueries({ queryKey: ["tutorials", selectedId] });
    }
    setViewMode("detail");
  }, [queryClient, selectedId]);

  // ─── Session View ─────────────────────────────────────────
  if (viewMode === "session" && selectedId) {
    if (detailLoading) {
      return (
        <div className="flex h-full flex-col">
          <div className="border-b border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] px-4 py-3">
            <Skeleton className="h-5 w-48" />
            <Skeleton className="mt-2 h-3 w-32" />
          </div>
          <div className="flex-1 p-6">
            <div className="mx-auto max-w-3xl space-y-4">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className={i % 2 === 0 ? "flex justify-start" : "flex justify-end"}>
                  <Skeleton className="h-16 w-64" />
                </div>
              ))}
            </div>
          </div>
        </div>
      );
    }

    if (detailError) {
      return (
        <div className="p-6">
          <button
            type="button"
            onClick={handleBack}
            className="mb-6 flex items-center gap-1 text-sm text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-primary)] transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to tutorials
          </button>
          <PageError
            message={detailErr?.message ?? "Failed to load tutorial"}
            onRetry={() =>
              queryClient.invalidateQueries({
                queryKey: ["tutorials", selectedId],
              })
            }
            context="your tutorials"
            icon={GraduationCap}
          />
        </div>
      );
    }

    if (detailData) {
      return (
        <div
          className="flex h-full flex-col"
          style={{ minHeight: "calc(100dvh - var(--header-height, 48px))" }}
        >
          <TutorialSession
            tutorial={detailData}
            onBack={handleBack}
            onComplete={handleSessionComplete}
          />
        </div>
      );
    }
  }

  // ─── Detail View ──────────────────────────────────────────
  if (viewMode === "detail" && selectedId) {
    if (detailLoading) {
      return (
        <div className="mx-auto max-w-4xl p-6">
          <Skeleton className="mb-6 h-4 w-32" />
          <Skeleton className="mb-2 h-6 w-64" />
          <Skeleton className="mb-6 h-4 w-40" />
          <Skeleton className="mb-4 h-24 w-full" />
          <div className="grid grid-cols-4 gap-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-20" />
            ))}
          </div>
          <Skeleton className="mt-4 h-32 w-full" />
        </div>
      );
    }

    if (detailError) {
      return (
        <div className="mx-auto max-w-4xl p-6">
          <button
            type="button"
            onClick={handleBack}
            className="mb-6 flex items-center gap-1 text-sm text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-primary)] transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to tutorials
          </button>
          <PageError
            message={detailErr?.message ?? "Failed to load tutorial"}
            onRetry={() =>
              queryClient.invalidateQueries({
                queryKey: ["tutorials", selectedId],
              })
            }
            context="your tutorials"
            icon={GraduationCap}
          />
        </div>
      );
    }

    if (detailData) {
      return (
        <div className="mx-auto max-w-4xl p-6">
          <button
            type="button"
            onClick={handleBack}
            className="mb-6 flex items-center gap-1 text-sm text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-primary)] transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to tutorials
          </button>
          <TutorialDetailView tutorial={detailData} />
        </div>
      );
    }
  }

  // ─── List View (Default) ──────────────────────────────────
  return (
    <PageTransition>
      <div className="mx-auto max-w-3xl space-y-6 p-6">
        {/* Header */}
        <PageHeader
          title="Learning Lab"
          subtitle="Learn through Socratic dialogue"
          icon={GraduationCap}
        />

        {/* Filter bar */}
        <div className="flex items-center gap-2" role="tablist" aria-label="Tutorial phase filter">
          {PHASE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => {
                setPhaseFilter(opt.value);
                setPage(1);
              }}
              role="tab"
              aria-selected={phaseFilter === opt.value}
              tabIndex={phaseFilter === opt.value ? 0 : -1}
              className={
                phaseFilter === opt.value
                  ? "rounded-[var(--radius-full)] bg-[var(--color-info-500)] px-3 py-1 text-xs font-medium text-[var(--color-fg-on-accent)]"
                  : "rounded-[var(--radius-full)] bg-[var(--color-bg-overlay)] px-3 py-1 text-xs font-medium text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-primary)] transition-colors"
              }
            >
              {opt.label}
            </button>
          ))}
        </div>

        {/* Loading */}
        {listLoading && (
          <div className="space-y-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-36 w-full" />
            ))}
          </div>
        )}

        {/* Error */}
        {listError && (
          <PageError
            message={listErr?.message ?? "Failed to load tutorials"}
            onRetry={() => refetchList()}
            context="your tutorials"
            icon={GraduationCap}
          />
        )}

        {/* Empty state */}
        {!listLoading && !listError && tutorials.length === 0 && (
          <EmptyState
            icon={BookOpen}
            title="No tutorials yet"
            description="Submit work to start a Socratic learning session. The AI tutor will guide you through understanding your topic deeply."
          />
        )}

        {/* Tutorial cards */}
        {!listLoading && !listError && tutorials.length > 0 && (
          <>
            <div className="space-y-4">
              {tutorials.map((tutorial) => (
                <TutorialCard
                  key={tutorial.id}
                  tutorial={tutorial}
                  onClick={() => handleSelectTutorial(tutorial)}
                />
              ))}
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="mt-6">
                <Pagination page={page} totalPages={totalPages} onPageChange={setPage} />
              </div>
            )}
          </>
        )}
      </div>
    </PageTransition>
  );
}

export { TutorialsPage };

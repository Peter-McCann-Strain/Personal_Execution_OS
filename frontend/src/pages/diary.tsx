import { useState, useCallback, useMemo, useEffect } from "react";
import { useSearchParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { Plus, X, Loader2, BookOpen } from "lucide-react";
import { getEpisodes } from "@/api/episodes";
import type { EpisodeQueryParams } from "@/api/episodes";
import { DiaryEntryCard, DiaryEntryCardSkeleton } from "@/components/diary/diary-entry-card";
import { DiaryTrends } from "@/components/diary/diary-trends";
import { QuickCaptureModal } from "@/components/diary/quick-capture-modal";
import { Button } from "@/components/ui/button";
import { PageError } from "@/components/ui/page-error";
import { PageHeader } from "@/components/ui/page-header";
import { PageTransition } from "@/components/ui/page-transition";
import { SegmentedControl } from "@/components/ui/segmented-control";
import type { Episode, ParaCategory, EpisodeType } from "@/types";

// ─── Tab type ───────────────────────────────────────────────
type DiaryTab = "feed" | "trends";

// ─── Filter State ───────────────────────────────────────────
interface FilterState {
  dateRange: "7d" | "30d" | "90d" | "all";
  paraCategory: ParaCategory | "all";
  episodeType: EpisodeType | "all";
  tags: string[];
  moodMin: number;
  moodMax: number;
  sort: "newest" | "oldest" | "mood_high" | "mood_low" | "energy_high" | "energy_low";
}

const DEFAULT_FILTERS: FilterState = {
  dateRange: "7d",
  paraCategory: "all",
  episodeType: "all",
  tags: [],
  moodMin: 0,
  moodMax: 10,
  sort: "newest",
};

function dateRangeToISO(range: FilterState["dateRange"]): string | undefined {
  if (range === "all") return undefined;
  const d = new Date();
  const days = range === "7d" ? 7 : range === "30d" ? 30 : 90;
  d.setDate(d.getDate() - days);
  // Day precision only — otherwise `new Date()` on every render makes the
  // queryKey change every ms and hammers the backend in an infinite refetch
  // loop (observed 2026-04-18 triggering 429s).
  return d.toISOString().slice(0, 10) + "T00:00:00.000Z";
}

function sortToParams(sort: FilterState["sort"]): {
  sort: "created_at" | "mood_score" | "energy_rating";
  order: "asc" | "desc";
} {
  switch (sort) {
    case "newest":
      return { sort: "created_at", order: "desc" };
    case "oldest":
      return { sort: "created_at", order: "asc" };
    case "mood_high":
      return { sort: "mood_score", order: "desc" };
    case "mood_low":
      return { sort: "mood_score", order: "asc" };
    case "energy_high":
      return { sort: "energy_rating", order: "desc" };
    case "energy_low":
      return { sort: "energy_rating", order: "asc" };
  }
}

function filtersToParams(filters: FilterState, offset: number): EpisodeQueryParams {
  const { sort, order } = sortToParams(filters.sort);
  return {
    limit: 20,
    offset,
    sort,
    order,
    date_from: dateRangeToISO(filters.dateRange),
    para_category: filters.paraCategory === "all" ? undefined : filters.paraCategory,
    episode_type: filters.episodeType === "all" ? undefined : filters.episodeType,
    tags: filters.tags.length > 0 ? filters.tags : undefined,
    mood_min: filters.moodMin > 0 ? filters.moodMin : undefined,
    mood_max: filters.moodMax < 10 ? filters.moodMax : undefined,
  };
}

function isFiltered(filters: FilterState): boolean {
  return (
    filters.dateRange !== DEFAULT_FILTERS.dateRange ||
    filters.paraCategory !== DEFAULT_FILTERS.paraCategory ||
    filters.episodeType !== DEFAULT_FILTERS.episodeType ||
    filters.tags.length > 0 ||
    filters.moodMin > 0 ||
    filters.moodMax < 10 ||
    filters.sort !== DEFAULT_FILTERS.sort
  );
}

// ─── Filter Bar ─────────────────────────────────────────────
function FilterBar({
  filters,
  onChange,
  onReset,
}: {
  filters: FilterState;
  onChange: (f: Partial<FilterState>) => void;
  onReset: () => void;
}) {
  const hasFilters = isFiltered(filters);

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] px-4 py-3">
      {/* Date range */}
      <select
        aria-label="Filter diary by date range"
        value={filters.dateRange}
        onChange={(e) => onChange({ dateRange: e.target.value as FilterState["dateRange"] })}
        className="h-8 rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] px-2 text-xs text-[var(--color-fg-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-border-focus)]"
      >
        <option value="7d">Last 7 days</option>
        <option value="30d">Last 30 days</option>
        <option value="90d">Last 90 days</option>
        <option value="all">All time</option>
      </select>

      {/* PARA category */}
      <select
        aria-label="Filter diary by PARA category"
        value={filters.paraCategory}
        onChange={(e) =>
          onChange({
            paraCategory: e.target.value as FilterState["paraCategory"],
          })
        }
        className="h-8 rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] px-2 text-xs text-[var(--color-fg-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-border-focus)]"
      >
        <option value="all">All PARA</option>
        <option value="project">Project</option>
        <option value="area">Area</option>
        <option value="resource">Resource</option>
        <option value="archive">Archive</option>
      </select>

      {/* Episode type */}
      <select
        aria-label="Filter diary by entry type"
        value={filters.episodeType}
        onChange={(e) =>
          onChange({
            episodeType: e.target.value as FilterState["episodeType"],
          })
        }
        className="h-8 rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] px-2 text-xs text-[var(--color-fg-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-border-focus)]"
      >
        <option value="all">All types</option>
        <option value="diary">Diary</option>
        <option value="capture">Capture</option>
        <option value="research">Research</option>
      </select>

      {/* Sort */}
      <select
        aria-label="Sort diary entries"
        value={filters.sort}
        onChange={(e) => onChange({ sort: e.target.value as FilterState["sort"] })}
        className="h-8 rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] px-2 text-xs text-[var(--color-fg-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-border-focus)]"
      >
        <option value="newest">Newest first</option>
        <option value="oldest">Oldest first</option>
        <option value="mood_high">Highest mood</option>
        <option value="mood_low">Lowest mood</option>
        <option value="energy_high">Highest energy</option>
        <option value="energy_low">Lowest energy</option>
      </select>

      {/* Tag chips (display active tag filters) */}
      {filters.tags.map((tag) => (
        <span
          key={tag}
          className="inline-flex items-center gap-1 rounded-[var(--radius-full)] bg-[var(--color-bg-overlay)] px-2 py-0.5 text-[10px] font-medium text-[var(--color-fg-secondary)]"
        >
          {tag}
          <button
            onClick={() => onChange({ tags: filters.tags.filter((t) => t !== tag) })}
            className="hover:text-[var(--color-fg-primary)] cursor-pointer"
            aria-label={`Remove ${tag} filter`}
          >
            <X className="h-2.5 w-2.5" />
          </button>
        </span>
      ))}

      {/* Clear all */}
      {hasFilters && (
        <button
          onClick={onReset}
          className="ml-auto text-xs text-[var(--color-fg-secondary)] hover:text-[var(--color-fg-primary)] transition-colors cursor-pointer"
        >
          Clear all
        </button>
      )}
    </div>
  );
}

// ─── Main Diary Page ────────────────────────────────────────
function DiaryPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [tab, setTab] = useState<DiaryTab>("feed");
  const [filters, setFilters] = useState<FilterState>(DEFAULT_FILTERS);
  const [offset, setOffset] = useState(0);
  const [captureOpen, setCaptureOpen] = useState(false);

  const queryParams = useMemo(() => filtersToParams(filters, offset), [filters, offset]);

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ["episodes", queryParams],
    queryFn: () => getEpisodes(queryParams),
    staleTime: 15_000,
  });

  const handleFilterChange = useCallback((partial: Partial<FilterState>) => {
    setFilters((prev) => ({ ...prev, ...partial }));
    setOffset(0);
  }, []);

  const handleTagClick = useCallback((tag: string) => {
    setFilters((prev) => ({
      ...prev,
      tags: prev.tags.includes(tag) ? prev.tags : [...prev.tags, tag],
    }));
    setOffset(0);
  }, []);

  const handleResetFilters = useCallback(() => {
    setFilters(DEFAULT_FILTERS);
    setOffset(0);
  }, []);

  const episodes = data?.items ?? [];
  const hasMore = data?.has_more ?? false;

  useEffect(() => {
    if (searchParams.get("capture") !== "1") return;
    queueMicrotask(() => setCaptureOpen(true));
    setSearchParams({}, { replace: true });
  }, [searchParams, setSearchParams]);

  if (error)
    return (
      <PageError
        message={error.message}
        onRetry={() => refetch()}
        context="diary entries"
        icon={BookOpen}
      />
    );

  return (
    <PageTransition>
      <div className="mx-auto max-w-[800px] space-y-4 p-6">
        {/* Header */}
        <PageHeader
          title="Diary"
          subtitle="Capture thoughts as they happen"
          icon={BookOpen}
          agentColor="diary"
        >
          <Button size="sm" onClick={() => setCaptureOpen(true)}>
            <Plus className="h-4 w-4" />
            New Entry
          </Button>
        </PageHeader>

        {/* Tab bar */}
        <SegmentedControl
          value={tab}
          onChange={setTab}
          options={[
            { value: "feed", label: "Feed" },
            { value: "trends", label: "Trends" },
          ]}
          label="Diary view"
          size="md"
        />

        {/* Feed tab */}
        {tab === "feed" && (
          <>
            {/* Filter bar */}
            <FilterBar
              filters={filters}
              onChange={handleFilterChange}
              onReset={handleResetFilters}
            />

            {/* Loading state */}
            {isLoading && (
              <div className="space-y-4">
                {Array.from({ length: 5 }).map((_, i) => (
                  <DiaryEntryCardSkeleton key={i} />
                ))}
              </div>
            )}

            {/* Empty state */}
            {!isLoading && episodes.length === 0 && (
              <div className="flex flex-col items-center py-16 text-center">
                <div className="h-16 w-16 rounded-full bg-[var(--color-bg-overlay)] flex items-center justify-center mb-4">
                  <Plus className="h-8 w-8 text-[var(--color-fg-tertiary)]" />
                </div>
                <p className="text-sm font-medium text-[var(--color-fg-primary)] mb-1">
                  No diary entries yet
                </p>
                <p className="text-xs text-[var(--color-fg-tertiary)] mb-4">
                  Capture your first thought to get started.
                </p>
                <Button size="sm" onClick={() => setCaptureOpen(true)}>
                  <Plus className="h-4 w-4" />
                  New Entry
                </Button>
              </div>
            )}

            {/* Entry cards */}
            {!isLoading && episodes.length > 0 && (
              <div className="space-y-3">
                {episodes.map((episode: Episode) => (
                  <DiaryEntryCard key={episode.id} episode={episode} onTagClick={handleTagClick} />
                ))}
              </div>
            )}

            {/* Load more */}
            {hasMore && (
              <div className="flex justify-center py-4">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setOffset((prev) => prev + 20)}
                  loading={isFetching && !isLoading}
                >
                  {isFetching && !isLoading ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Loading...
                    </>
                  ) : (
                    "Load more entries..."
                  )}
                </Button>
              </div>
            )}
          </>
        )}

        {/* Trends tab */}
        {tab === "trends" && <DiaryTrends />}

        {/* Quick capture FAB + modal */}
        <QuickCaptureModal externalOpen={captureOpen} onExternalOpenChange={setCaptureOpen} />
      </div>
    </PageTransition>
  );
}

export { DiaryPage };

import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Activity, ArrowLeft, ClipboardList, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { PageError } from "@/components/ui/page-error";
import { PageHeader } from "@/components/ui/page-header";
import { PageTransition } from "@/components/ui/page-transition";
import { ReviewCard } from "@/components/reviews/review-card";
import { WeeklyReviewDetail, type MoodChartData } from "@/components/reviews/weekly-review-detail";
import { getReviews, generateReview, type ReviewQueryParams } from "@/api/reviews";
import type { WeeklyReview } from "@/types";

// ─── Filter Config ──────────────────────────────────────────

const TYPE_OPTIONS: {
  value: "all" | "weekly" | "quarterly";
  label: string;
}[] = [
  { value: "all", label: "All Types" },
  { value: "weekly", label: "Weekly" },
  { value: "quarterly", label: "Quarterly" },
];

// ─── Approximate Chart Data ─────────────────────────────────
// Uses seeded offsets from the review's average_mood until per-day API data is available.

const DAILY_MOOD_OFFSETS = [-0.5, 0.3, -0.2, 0.8, -0.4, 0.6, 0.1];
const DAILY_ENERGY_OFFSETS = [0.2, -0.3, 0.5, -0.1, 0.7, -0.6, 0.4];

function generateApproxChartData(review: WeeklyReview): MoodChartData[] {
  const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const baseMood = review.average_mood ?? 6;
  return days.map((day, i) => ({
    day,
    mood: Math.max(1, Math.min(10, baseMood + DAILY_MOOD_OFFSETS[i])),
    energy: Math.max(1, Math.min(10, baseMood + DAILY_ENERGY_OFFSETS[i])),
  }));
}

// ─── Reviews Page ───────────────────────────────────────────

function ReviewsPage() {
  const queryClient = useQueryClient();
  const [typeFilter, setTypeFilter] = useState<"all" | "weekly" | "quarterly">("all");
  const [selectedReview, setSelectedReview] = useState<WeeklyReview | null>(null);

  const queryParams: ReviewQueryParams = useMemo(() => {
    const params: ReviewQueryParams = {
      limit: 20,
      sort: "created_at",
      order: "desc",
    };
    if (typeFilter !== "all") params.review_type = typeFilter;
    return params;
  }, [typeFilter]);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["reviews", queryParams],
    queryFn: () => getReviews(queryParams),
  });

  const generateMutation = useMutation({
    mutationFn: (type: "weekly" | "quarterly") => generateReview(type),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["reviews"] });
    },
  });

  const reviews = data?.items ?? [];

  const handleGenerate = () => {
    generateMutation.mutate("weekly");
  };

  // If viewing a review detail
  if (selectedReview) {
    const idx = reviews.findIndex((r) => r.id === selectedReview.id);
    const previousReview = idx < reviews.length - 1 ? reviews[idx + 1] : null;
    const chartData = generateApproxChartData(selectedReview);

    return (
      <div className="mx-auto max-w-4xl p-6">
        <button
          type="button"
          onClick={() => setSelectedReview(null)}
          className="mb-6 flex items-center gap-1 text-sm text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-primary)] transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          All Reviews
        </button>

        <WeeklyReviewDetail
          review={selectedReview}
          previousMood={previousReview?.average_mood}
          moodChartData={chartData}
        />
      </div>
    );
  }

  return (
    <PageTransition>
      <div className="mx-auto max-w-3xl space-y-6 p-6">
        {/* Header */}
        <PageHeader
          title="Reviews"
          subtitle="Weekly and quarterly reflections"
          icon={Activity}
          agentColor="review"
        >
          <Button size="sm" onClick={handleGenerate} loading={generateMutation.isPending}>
            {generateMutation.isPending ? (
              "Generating..."
            ) : (
              <>
                <Sparkles className="h-4 w-4" />
                Generate Review
              </>
            )}
          </Button>
        </PageHeader>

        {/* Filter bar */}
        <div className="flex items-center gap-2" role="tablist" aria-label="Review type filter">
          {TYPE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => setTypeFilter(opt.value)}
              role="tab"
              aria-selected={typeFilter === opt.value}
              tabIndex={typeFilter === opt.value ? 0 : -1}
              className={
                typeFilter === opt.value
                  ? "rounded-[var(--radius-full)] bg-[var(--color-info-500)] px-3 py-1 text-xs font-medium text-[var(--color-fg-on-accent)]"
                  : "rounded-[var(--radius-full)] bg-[var(--color-bg-overlay)] px-3 py-1 text-xs font-medium text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-primary)] transition-colors"
              }
            >
              {opt.label}
            </button>
          ))}
        </div>

        {/* Loading */}
        {isLoading && (
          <div className="space-y-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-32 w-full" />
            ))}
          </div>
        )}

        {/* Error */}
        {isError && (
          <PageError
            message={error?.message ?? "Failed to load reviews"}
            onRetry={() => refetch()}
            context="your reviews"
            icon={Activity}
          />
        )}

        {/* Empty state */}
        {!isLoading && !isError && reviews.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <ClipboardList className="mb-3 h-12 w-12 text-[var(--color-fg-disabled)]" />
            <h2 className="mb-1 text-lg font-medium text-[var(--color-fg-primary)]">
              No reviews yet
            </h2>
            <p className="mb-4 text-sm text-[var(--color-fg-tertiary)]">
              Generate your first weekly review to see patterns and insights
            </p>
            <Button size="sm" onClick={handleGenerate}>
              <Sparkles className="h-4 w-4" />
              Generate Review
            </Button>
          </div>
        )}

        {/* Review cards */}
        {!isLoading && !isError && reviews.length > 0 && (
          <div className="space-y-4">
            {reviews.map((review, idx) => {
              const previousReview = idx < reviews.length - 1 ? reviews[idx + 1] : null;
              return (
                <ReviewCard
                  key={review.id}
                  review={review}
                  previousMood={previousReview?.average_mood}
                  onClick={() => setSelectedReview(review)}
                />
              );
            })}
          </div>
        )}
      </div>
    </PageTransition>
  );
}

export { ReviewsPage };

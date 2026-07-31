import { ArrowDown, ArrowRight, ArrowUp, CheckCircle2, Lightbulb } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import type { WeeklyReview } from "@/types";

// ─── Mood Trend Arrow ───────────────────────────────────────

interface MoodTrendProps {
  current: number | null;
  previous?: number | null;
}

function MoodTrend({ current, previous }: MoodTrendProps) {
  if (current == null) return null;

  if (previous == null) {
    return (
      <span className="inline-flex items-center gap-0.5 text-[var(--color-fg-disabled)]">
        <ArrowRight className="h-3 w-3" />
      </span>
    );
  }

  const diff = current - previous;
  if (diff > 0) {
    return (
      <span className="inline-flex items-center gap-0.5 text-[var(--color-success-500)]">
        <ArrowUp className="h-3 w-3" />
      </span>
    );
  }
  if (diff < 0) {
    return (
      <span className="inline-flex items-center gap-0.5 text-[var(--color-error-500)]">
        <ArrowDown className="h-3 w-3" />
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-0.5 text-[var(--color-fg-disabled)]">
      <ArrowRight className="h-3 w-3" />
    </span>
  );
}

// ─── Review Card ────────────────────────────────────────────

interface ReviewCardProps {
  review: WeeklyReview;
  previousMood?: number | null;
  onClick?: () => void;
}

function ReviewCard({ review, previousMood, onClick }: ReviewCardProps) {
  return (
    <Card hoverable padding="none" onClick={onClick} className="group">
      <div className="p-4">
        {/* Header: type badge + period */}
        <div className="mb-3 flex items-center justify-between">
          <Badge variant="info" size="sm">
            WEEKLY
          </Badge>
          <span className="text-xs text-[var(--color-fg-tertiary)]">{review.period}</span>
        </div>

        {/* Metrics row */}
        <div className="mb-3 flex items-center gap-6">
          {/* Average mood */}
          {review.average_mood != null && (
            <div className="flex items-center gap-1.5">
              <span className="text-lg font-bold text-[var(--color-fg-primary)]">
                {review.average_mood.toFixed(1)}
              </span>
              <MoodTrend current={review.average_mood} previous={previousMood} />
              <span className="text-xs text-[var(--color-fg-tertiary)]">avg mood</span>
            </div>
          )}

          {/* Accomplishments */}
          <div className="flex items-center gap-1.5">
            <CheckCircle2 className="h-4 w-4 text-[var(--color-success-500)]" />
            <span className="text-sm font-medium text-[var(--color-fg-primary)]">
              {(review.accomplishments ?? []).length}
            </span>
            <span className="text-xs text-[var(--color-fg-tertiary)]">accomplishments</span>
          </div>
        </div>

        {/* Key insight preview */}
        {review.key_insight && (
          <div className="flex items-start gap-2">
            <Lightbulb className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--color-warning-500)]" />
            <p className="line-clamp-2 text-sm italic text-[var(--color-fg-secondary)]">
              &ldquo;{review.key_insight}&rdquo;
            </p>
          </div>
        )}

        {/* View link */}
        <div className="mt-3 flex justify-end">
          <span className="flex items-center gap-1 text-xs text-[var(--color-info-500)] opacity-0 transition-opacity group-hover:opacity-100">
            View
            <ArrowRight className="h-3 w-3" />
          </span>
        </div>
      </div>
    </Card>
  );
}

export { ReviewCard, MoodTrend };
export type { ReviewCardProps };

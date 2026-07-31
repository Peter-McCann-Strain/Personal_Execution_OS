import { ArrowRight, Clock, Star } from "lucide-react";
import { format, isPast, parseISO } from "date-fns";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import type { Decision, DecisionStatus } from "@/api/decisions";

// ─── Status Badge Mapping ──────────────────────────────────

const statusConfig: Record<
  DecisionStatus,
  { label: string; variant: "warning" | "success" | "default" }
> = {
  pending_review: { label: "Pending Review", variant: "warning" },
  reviewed: { label: "Reviewed", variant: "success" },
  archived: { label: "Archived", variant: "default" },
};

// ─── Star Rating ───────────────────────────────────────────

function StarRating({ rating, max = 5 }: { rating: number; max?: number }) {
  return (
    <span className="inline-flex items-center gap-0.5">
      {Array.from({ length: max }).map((_, i) => (
        <Star
          key={i}
          className={cn(
            "h-3 w-3",
            i < rating
              ? "fill-[var(--color-warning-500)] text-[var(--color-warning-500)]"
              : "text-[var(--color-fg-disabled)]",
          )}
        />
      ))}
    </span>
  );
}

// ─── Decision Card ─────────────────────────────────────────

interface DecisionCardProps {
  decision: Decision;
  onClick?: () => void;
}

function DecisionCard({ decision, onClick }: DecisionCardProps) {
  const config = statusConfig[decision.status];
  const reviewDate = decision.review_date ? parseISO(decision.review_date) : null;
  const isOverdue = reviewDate && decision.status === "pending_review" && isPast(reviewDate);

  return (
    <Card hoverable padding="none" onClick={onClick} className="group">
      <div className="p-4">
        {/* Header: status badge + date */}
        <div className="mb-2 flex items-center justify-between">
          <Badge variant={config.variant} size="sm">
            {config.label}
          </Badge>
          <span className="text-xs text-[var(--color-fg-tertiary)]">
            {format(parseISO(decision.created_at), "MMM d, yyyy")}
          </span>
        </div>

        {/* Title */}
        <h3 className="mb-1 text-sm font-semibold text-[var(--color-fg-primary)]">
          {decision.title}
        </h3>

        {/* Decision made (preview) */}
        <p className="mb-3 line-clamp-2 text-sm text-[var(--color-fg-secondary)]">
          {decision.decision_made}
        </p>

        {/* Options considered chips */}
        {decision.options_considered.length > 0 && (
          <div className="mb-3 flex flex-wrap gap-1">
            {decision.options_considered.slice(0, 4).map((option) => (
              <span
                key={option}
                className="rounded-[var(--radius-full)] border border-[var(--color-border-subtle)] bg-[var(--color-bg-overlay)] px-2 py-0.5 text-[10px] text-[var(--color-fg-tertiary)]"
              >
                {option}
              </span>
            ))}
            {decision.options_considered.length > 4 && (
              <span className="rounded-[var(--radius-full)] border border-[var(--color-border-subtle)] bg-[var(--color-bg-overlay)] px-2 py-0.5 text-[10px] text-[var(--color-fg-tertiary)]">
                +{decision.options_considered.length - 4} more
              </span>
            )}
          </div>
        )}

        {/* Review date + outcome rating */}
        <div className="mb-2 flex items-center justify-between">
          {reviewDate && (
            <span
              className={cn(
                "inline-flex items-center gap-1 text-xs",
                isOverdue
                  ? "font-medium text-[var(--color-error-500)]"
                  : "text-[var(--color-fg-tertiary)]",
              )}
            >
              <Clock className="h-3 w-3" />
              {isOverdue ? "Overdue: " : "Review: "}
              {format(reviewDate, "MMM d, yyyy")}
            </span>
          )}
          {decision.outcome_rating != null && <StarRating rating={decision.outcome_rating} />}
        </div>

        {/* Tags */}
        {decision.tags.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-1">
            {decision.tags.map((tag) => (
              <Badge key={tag} variant="info" size="sm">
                {tag}
              </Badge>
            ))}
          </div>
        )}

        {/* View link */}
        <div className="flex justify-end">
          <span className="flex items-center gap-1 text-xs text-[var(--color-info-500)] opacity-0 transition-opacity group-hover:opacity-100">
            View
            <ArrowRight className="h-3 w-3" />
          </span>
        </div>
      </div>
    </Card>
  );
}

export { DecisionCard, StarRating };
export type { DecisionCardProps };

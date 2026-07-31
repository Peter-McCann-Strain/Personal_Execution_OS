import { memo, useCallback } from "react";
import { ArrowRight, Calendar, Check, Eye, Quote, X } from "lucide-react";
import { cn, formatRelativeTime } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { Commitment, CommitmentStatus } from "@/types";

// ─── Status Config ──────────────────────────────────────────

const statusVariantMap: Record<CommitmentStatus, "default" | "info" | "success" | "error"> = {
  detected: "default",
  acknowledged: "info",
  completed: "success",
  cancelled: "error",
};

const statusLabelMap: Record<CommitmentStatus, string> = {
  detected: "Detected",
  acknowledged: "Acknowledged",
  completed: "Completed",
  cancelled: "Cancelled",
};

// ─── Helpers ────────────────────────────────────────────────

function isOverdue(commitment: Commitment): boolean {
  if (!commitment.temporal_normalized) return false;
  try {
    const due = new Date(commitment.temporal_normalized);
    return (
      due.getTime() < Date.now() &&
      commitment.status !== "completed" &&
      commitment.status !== "cancelled"
    );
  } catch {
    return false;
  }
}

function formatDueDate(isoString: string): string {
  try {
    return new Date(isoString).toLocaleDateString("en-GB", {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  } catch {
    return isoString;
  }
}

// ─── CommitmentCard Component ───────────────────────────────

interface CommitmentCardProps {
  commitment: Commitment;
  onStatusChange: (id: string, status: CommitmentStatus) => void;
  isPending?: boolean;
}

const CommitmentCard = memo(function CommitmentCard({
  commitment,
  onStatusChange,
  isPending = false,
}: CommitmentCardProps) {
  const overdue = isOverdue(commitment);
  const isActive = commitment.status === "detected" || commitment.status === "acknowledged";

  const handleAcknowledge = useCallback(() => {
    onStatusChange(commitment.id, "acknowledged");
  }, [commitment.id, onStatusChange]);

  const handleComplete = useCallback(() => {
    onStatusChange(commitment.id, "completed");
  }, [commitment.id, onStatusChange]);

  const handleCancel = useCallback(() => {
    onStatusChange(commitment.id, "cancelled");
  }, [commitment.id, onStatusChange]);

  return (
    <Card
      padding="none"
      className={cn(
        "group relative transition-all duration-200",
        "hover:border-[var(--color-border-strong)] hover:shadow-sm",
        overdue && "border-l-4 border-l-[var(--color-error-500)]",
        isPending && "opacity-60",
      )}
    >
      <div className="p-4">
        {/* Header row */}
        <div className="mb-2 flex items-center gap-2">
          <Badge variant={statusVariantMap[commitment.status]} size="sm">
            {statusLabelMap[commitment.status]}
          </Badge>
          <Badge variant="default" size="sm" className="capitalize">
            {commitment.commitment_type}
          </Badge>
          {overdue && (
            <Badge variant="error" size="sm">
              Overdue
            </Badge>
          )}
          <span className="ml-auto text-xs text-[var(--color-fg-tertiary)]">
            {formatRelativeTime(commitment.created_at)}
          </span>
        </div>

        {/* Normalized action — main text */}
        <p className="mb-1.5 text-sm font-medium leading-relaxed text-[var(--color-fg-primary)]">
          {commitment.normalized_action}
        </p>

        {/* Verbatim quote */}
        {commitment.verbatim_text && (
          <div className="mb-3 flex items-start gap-1.5">
            <Quote className="mt-0.5 h-3 w-3 shrink-0 text-[var(--color-fg-disabled)]" />
            <p className="text-xs italic leading-relaxed text-[var(--color-fg-tertiary)]">
              {commitment.verbatim_text}
            </p>
          </div>
        )}

        {/* Metadata row */}
        <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--color-fg-secondary)]">
          {/* Who committed → who to */}
          {(commitment.who_committed || commitment.who_to) && (
            <span className="flex items-center gap-1">
              {commitment.who_committed && (
                <span className="font-medium">{commitment.who_committed}</span>
              )}
              {commitment.who_committed && commitment.who_to && (
                <ArrowRight className="h-3 w-3 text-[var(--color-fg-disabled)]" />
              )}
              {commitment.who_to && <span className="font-medium">{commitment.who_to}</span>}
            </span>
          )}

          {/* Temporal info */}
          {commitment.temporal_normalized && (
            <span
              className={cn(
                "flex items-center gap-1",
                overdue && "font-semibold text-[var(--color-error-900)]",
              )}
            >
              <Calendar className="h-3 w-3" />
              {formatDueDate(commitment.temporal_normalized)}
            </span>
          )}
          {!commitment.temporal_normalized && commitment.temporal_expression_raw && (
            <span className="flex items-center gap-1 text-[var(--color-fg-tertiary)]">
              <Calendar className="h-3 w-3" />
              {commitment.temporal_expression_raw}
            </span>
          )}

          {/* Confidence score */}
          <span className="flex items-center gap-1.5">
            <span className="text-[var(--color-fg-tertiary)]">Confidence</span>
            <span className="relative h-1.5 w-12 overflow-hidden rounded-full bg-[var(--color-bg-overlay)]">
              <span
                className={cn(
                  "absolute inset-y-0 left-0 rounded-full transition-all",
                  commitment.confidence_score >= 0.8
                    ? "bg-[var(--color-success-500)]"
                    : commitment.confidence_score >= 0.5
                      ? "bg-[var(--color-warning-500)]"
                      : "bg-[var(--color-error-500)]",
                )}
                style={{
                  width: `${Math.round(commitment.confidence_score * 100)}%`,
                }}
              />
            </span>
            <span className="font-mono">{Math.round(commitment.confidence_score * 100)}%</span>
          </span>
        </div>

        {/* Action buttons */}
        {isActive && (
          <div className="flex items-center justify-end gap-2">
            {commitment.status === "detected" && (
              <Button variant="outline" size="sm" onClick={handleAcknowledge} disabled={isPending}>
                <Eye className="h-3.5 w-3.5" />
                Acknowledge
              </Button>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={handleComplete}
              disabled={isPending}
              className="text-[var(--color-success-500)] hover:text-[var(--color-success-500)]"
            >
              <Check className="h-3.5 w-3.5" />
              Complete
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleCancel}
              disabled={isPending}
              className="opacity-0 transition-opacity group-hover:opacity-100 text-[var(--color-fg-tertiary)]"
            >
              <X className="h-3.5 w-3.5" />
              Cancel
            </Button>
          </div>
        )}
      </div>
    </Card>
  );
});

export { CommitmentCard };
export type { CommitmentCardProps };

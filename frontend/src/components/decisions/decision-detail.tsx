import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  BookOpen,
  CheckCircle2,
  Clock,
  Lightbulb,
  ListChecks,
  Scale,
  Star,
  Tag,
  Target,
} from "lucide-react";
import { format, isPast, parseISO } from "date-fns";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { recordOutcome } from "@/api/decisions";
import { StarRating } from "./decision-card";
import type { Decision, DecisionStatus } from "@/api/decisions";

// ─── Status Config ─────────────────────────────────────────

const statusConfig: Record<
  DecisionStatus,
  { label: string; variant: "warning" | "success" | "default" }
> = {
  pending_review: { label: "Pending Review", variant: "warning" },
  reviewed: { label: "Reviewed", variant: "success" },
  archived: { label: "Archived", variant: "default" },
};

// ─── Section Header ────────────────────────────────────────

function SectionHeader({ icon, title }: { icon: React.ReactNode; title: string }) {
  return (
    <div className="mb-3 flex items-center gap-2 border-b border-[var(--color-border-subtle)] pb-2">
      <span className="text-[var(--color-fg-tertiary)]">{icon}</span>
      <h3 className="text-xs font-semibold uppercase tracking-widest text-[var(--color-fg-tertiary)]">
        {title}
      </h3>
    </div>
  );
}

// ─── Interactive Star Rating ───────────────────────────────

function InteractiveStarRating({
  value,
  onChange,
  max = 5,
}: {
  value: number;
  onChange: (value: number) => void;
  max?: number;
}) {
  const [hovered, setHovered] = useState(0);

  return (
    <span className="inline-flex items-center gap-1">
      {Array.from({ length: max }).map((_, i) => {
        const starValue = i + 1;
        const isActive = starValue <= (hovered || value);
        return (
          <button
            key={i}
            type="button"
            onClick={() => onChange(starValue)}
            onMouseEnter={() => setHovered(starValue)}
            onMouseLeave={() => setHovered(0)}
            className={cn(
              "cursor-pointer transition-colors",
              isActive
                ? "text-[var(--color-warning-500)]"
                : "text-[var(--color-fg-disabled)] hover:text-[var(--color-warning-300)]",
            )}
            aria-label={`Rate ${starValue} of ${max}`}
          >
            <Star className={cn("h-5 w-5", isActive && "fill-[var(--color-warning-500)]")} />
          </button>
        );
      })}
      {value > 0 && (
        <span className="ml-2 text-sm text-[var(--color-fg-secondary)]">
          {value}/{max}
        </span>
      )}
    </span>
  );
}

// ─── Outcome Form ──────────────────────────────────────────

function OutcomeForm({ decisionId, onSuccess }: { decisionId: string; onSuccess: () => void }) {
  const queryClient = useQueryClient();
  const [actualOutcome, setActualOutcome] = useState("");
  const [outcomeRating, setOutcomeRating] = useState(0);

  const mutation = useMutation({
    mutationFn: () =>
      recordOutcome(decisionId, {
        actual_outcome: actualOutcome,
        outcome_rating: outcomeRating > 0 ? outcomeRating : undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["decisions"] });
      queryClient.invalidateQueries({
        queryKey: ["decision", decisionId],
      });
      queryClient.invalidateQueries({
        queryKey: ["decisions-due-review"],
      });
      toast.success("Outcome recorded successfully");
      onSuccess();
    },
    onError: () => {
      toast.error("Failed to record outcome");
    },
  });

  return (
    <Card
      padding="lg"
      className="border-[var(--color-warning-500)]/30 bg-gradient-to-r from-[var(--color-warning-50)] to-[var(--color-bg-surface)]"
    >
      <h3 className="mb-4 text-sm font-semibold text-[var(--color-fg-primary)]">Record Outcome</h3>

      {/* Actual outcome textarea */}
      <div className="mb-4">
        <label className="mb-1.5 block text-xs font-medium text-[var(--color-fg-secondary)]">
          What actually happened?
        </label>
        <textarea
          value={actualOutcome}
          onChange={(e) => setActualOutcome(e.target.value)}
          placeholder="Describe the actual outcome of this decision..."
          rows={4}
          className={cn(
            "w-full resize-none rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)]",
            "px-3 py-2 text-sm text-[var(--color-fg-primary)]",
            "placeholder:text-[var(--color-fg-tertiary)]",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-border-focus)]",
          )}
        />
      </div>

      {/* Outcome rating */}
      <div className="mb-4">
        <label className="mb-1.5 block text-xs font-medium text-[var(--color-fg-secondary)]">
          How well did this decision turn out?
        </label>
        <InteractiveStarRating value={outcomeRating} onChange={setOutcomeRating} />
      </div>

      {/* Submit */}
      <div className="flex justify-end">
        <Button
          onClick={() => mutation.mutate()}
          disabled={!actualOutcome.trim()}
          loading={mutation.isPending}
        >
          Save Outcome
        </Button>
      </div>
    </Card>
  );
}

// ─── Decision Detail ───────────────────────────────────────

interface DecisionDetailProps {
  decision: Decision;
  onBack: () => void;
}

function DecisionDetail({ decision, onBack }: DecisionDetailProps) {
  const [outcomeRecorded, setOutcomeRecorded] = useState(false);
  const config = statusConfig[decision.status];
  const reviewDate = decision.review_date ? parseISO(decision.review_date) : null;
  const isOverdue = reviewDate && decision.status === "pending_review" && isPast(reviewDate);

  const showOutcomeForm =
    decision.status === "pending_review" && !decision.actual_outcome && !outcomeRecorded;

  return (
    <div className="mx-auto max-w-3xl p-6">
      {/* Back button */}
      <button
        type="button"
        onClick={onBack}
        className="mb-6 flex items-center gap-1 text-sm text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-primary)] transition-colors"
      >
        <ArrowLeft className="h-4 w-4" />
        All Decisions
      </button>

      <div className="space-y-8">
        {/* Header */}
        <header>
          <div className="mb-3 flex items-center gap-3">
            <Badge variant={config.variant}>{config.label}</Badge>
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
          </div>
          <h1 className="mb-2 text-2xl font-bold text-[var(--color-fg-primary)]">
            {decision.title}
          </h1>
          <div className="flex items-center gap-4 text-xs text-[var(--color-fg-tertiary)]">
            <span>Created {format(parseISO(decision.created_at), "MMM d, yyyy")}</span>
            {decision.updated_at !== decision.created_at && (
              <span>Updated {format(parseISO(decision.updated_at), "MMM d, yyyy")}</span>
            )}
          </div>
        </header>

        {/* Context */}
        {decision.context && (
          <section>
            <SectionHeader icon={<BookOpen className="h-4 w-4" />} title="Context" />
            <p className="text-sm leading-relaxed text-[var(--color-fg-secondary)]">
              {decision.context}
            </p>
          </section>
        )}

        {/* Options Considered */}
        {decision.options_considered.length > 0 && (
          <section>
            <SectionHeader icon={<ListChecks className="h-4 w-4" />} title="Options Considered" />
            <ul className="space-y-2">
              {decision.options_considered.map((option, idx) => (
                <li key={idx} className="flex items-start gap-2">
                  <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-[var(--color-bg-overlay)] font-mono text-[10px] font-bold text-[var(--color-fg-secondary)]">
                    {idx + 1}
                  </span>
                  <span className="text-sm text-[var(--color-fg-primary)]">{option}</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* Decision Made */}
        <section>
          <SectionHeader icon={<Scale className="h-4 w-4" />} title="Decision Made" />
          <Card padding="md" className="border-l-2 border-l-[var(--color-info-500)]">
            <p className="text-sm font-medium leading-relaxed text-[var(--color-fg-primary)]">
              {decision.decision_made}
            </p>
          </Card>
        </section>

        {/* Reasoning */}
        {decision.reasoning && (
          <section>
            <SectionHeader icon={<Lightbulb className="h-4 w-4" />} title="Reasoning" />
            <p className="text-sm leading-relaxed text-[var(--color-fg-secondary)]">
              {decision.reasoning}
            </p>
          </section>
        )}

        {/* Expected Outcome */}
        {decision.expected_outcome && (
          <section>
            <SectionHeader icon={<Target className="h-4 w-4" />} title="Expected Outcome" />
            <p className="text-sm leading-relaxed text-[var(--color-fg-secondary)]">
              {decision.expected_outcome}
            </p>
          </section>
        )}

        {/* Actual Outcome (if recorded) */}
        {decision.actual_outcome && (
          <section>
            <SectionHeader icon={<CheckCircle2 className="h-4 w-4" />} title="Actual Outcome" />
            <Card padding="md" className="border-l-2 border-l-[var(--color-success-500)]">
              <p className="mb-2 text-sm leading-relaxed text-[var(--color-fg-primary)]">
                {decision.actual_outcome}
              </p>
              {decision.outcome_rating != null && (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-[var(--color-fg-tertiary)]">Outcome rating:</span>
                  <StarRating rating={decision.outcome_rating} />
                </div>
              )}
            </Card>
          </section>
        )}

        {/* Record Outcome Form (if pending review) */}
        {showOutcomeForm && (
          <section>
            <OutcomeForm decisionId={decision.id} onSuccess={() => setOutcomeRecorded(true)} />
          </section>
        )}

        {/* Tags */}
        {decision.tags.length > 0 && (
          <section>
            <SectionHeader icon={<Tag className="h-4 w-4" />} title="Tags" />
            <div className="flex flex-wrap gap-1.5">
              {decision.tags.map((tag) => (
                <Badge key={tag} variant="info" size="md">
                  {tag}
                </Badge>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

export { DecisionDetail };
export type { DecisionDetailProps };

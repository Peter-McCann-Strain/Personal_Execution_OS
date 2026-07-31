import { ArrowRight, MessageCircle, Brain, Target } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatRelativeTime } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { BloomProgressionBar } from "./bloom-indicator";
import type { Tutorial, TutorialPhase } from "@/api/tutorials";

// ─── Phase Config ───────────────────────────────────────────

const PHASE_CONFIG: Record<
  TutorialPhase,
  { label: string; variant: "default" | "info" | "success"; pulse?: boolean }
> = {
  submitted: { label: "Submitted", variant: "default" },
  dialogue: { label: "In Progress", variant: "info", pulse: true },
  complete: { label: "Complete", variant: "success" },
};

// ─── Tutorial Card ──────────────────────────────────────────

interface TutorialCardProps {
  tutorial: Tutorial;
  onClick?: () => void;
}

function TutorialCard({ tutorial, onClick }: TutorialCardProps) {
  const phase = PHASE_CONFIG[tutorial.phase];
  const gapsRatio =
    tutorial.knowledge_gaps_found > 0
      ? tutorial.knowledge_gaps_addressed / tutorial.knowledge_gaps_found
      : null;

  return (
    <Card hoverable padding="none" onClick={onClick} className="group">
      <div className="p-4">
        {/* Header: phase badge + date */}
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Badge variant={phase.variant} size="sm">
              <span className={cn(phase.pulse && "flex items-center gap-1.5")}>
                {phase.pulse && (
                  <span className="relative flex h-1.5 w-1.5">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[var(--color-info-500)] opacity-75" />
                    <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-[var(--color-info-500)]" />
                  </span>
                )}
                {phase.label}
              </span>
            </Badge>
            <Badge variant="default" size="sm">
              {tutorial.work_type}
            </Badge>
          </div>
          <span className="text-xs text-[var(--color-fg-tertiary)]">
            {formatRelativeTime(tutorial.created_at)}
          </span>
        </div>

        {/* Topic */}
        <h3 className="mb-3 text-sm font-semibold text-[var(--color-fg-primary)] line-clamp-2">
          {tutorial.topic}
        </h3>

        {/* Bloom progression */}
        {(tutorial.bloom_start || tutorial.bloom_end) && (
          <div className="mb-3">
            <div className="mb-1 flex items-center justify-between">
              <span className="text-[10px] font-medium uppercase tracking-wider text-[var(--color-fg-tertiary)]">
                Bloom Progression
              </span>
              {tutorial.bloom_start && tutorial.bloom_end && (
                <span className="text-[10px] text-[var(--color-fg-tertiary)]">
                  <span className="capitalize">{tutorial.bloom_start}</span>
                  {" → "}
                  <span className="capitalize">{tutorial.bloom_end}</span>
                </span>
              )}
            </div>
            <BloomProgressionBar start={tutorial.bloom_start} end={tutorial.bloom_end} />
          </div>
        )}

        {/* Metrics row */}
        <div className="flex items-center gap-4 text-xs text-[var(--color-fg-secondary)]">
          {/* Turn count */}
          <div className="flex items-center gap-1" title="Turns">
            <MessageCircle className="h-3.5 w-3.5 text-[var(--color-fg-tertiary)]" />
            <span>{tutorial.turn_count}</span>
          </div>

          {/* Knowledge gaps */}
          {tutorial.knowledge_gaps_found > 0 && (
            <div className="flex items-center gap-1" title="Knowledge gaps addressed">
              <Brain className="h-3.5 w-3.5 text-[var(--color-fg-tertiary)]" />
              <span>
                {tutorial.knowledge_gaps_addressed}/{tutorial.knowledge_gaps_found}
              </span>
              {gapsRatio !== null && (
                <div className="ml-0.5 h-1.5 w-8 overflow-hidden rounded-[var(--radius-full)] bg-[var(--color-bg-overlay)]">
                  <div
                    className="h-full rounded-[var(--radius-full)] bg-[var(--color-success-500)] transition-all"
                    style={{ width: `${Math.round(gapsRatio * 100)}%` }}
                  />
                </div>
              )}
            </div>
          )}

          {/* Speaking ratio */}
          {tutorial.speaking_ratio_student_pct != null && (
            <div className="flex items-center gap-1" title="Student speaking ratio">
              <Target className="h-3.5 w-3.5 text-[var(--color-fg-tertiary)]" />
              <span>{Math.round(tutorial.speaking_ratio_student_pct)}%</span>
            </div>
          )}
        </div>

        {/* View link */}
        <div className="mt-3 flex justify-end">
          <span className="flex items-center gap-1 text-xs text-[var(--color-info-500)] opacity-0 transition-opacity group-hover:opacity-100">
            {tutorial.phase === "dialogue" ? "Continue" : "View"}
            <ArrowRight className="h-3 w-3" />
          </span>
        </div>
      </div>
    </Card>
  );
}

export { TutorialCard };
export type { TutorialCardProps };

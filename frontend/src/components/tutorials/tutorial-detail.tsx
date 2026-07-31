import { useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  GraduationCap,
  User,
  Brain,
  Target,
  MessageCircle,
  Clock,
  FileText,
} from "lucide-react";
import { format, parseISO } from "date-fns";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { BloomIndicator, BloomBadge } from "./bloom-indicator";
import type { TutorialDetail as TutorialDetailType, TranscriptTurn } from "@/api/tutorials";

// ─── Collapsible Section ────────────────────────────────────

interface CollapsibleProps {
  title: string;
  icon: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
}

function Collapsible({ title, icon, defaultOpen = false, children }: CollapsibleProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)]">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="flex w-full items-center gap-2 px-4 py-3 text-left transition-colors hover:bg-[var(--color-bg-elevated)]"
      >
        {icon}
        <span className="flex-1 text-sm font-medium text-[var(--color-fg-primary)]">{title}</span>
        {isOpen ? (
          <ChevronDown className="h-4 w-4 text-[var(--color-fg-tertiary)]" />
        ) : (
          <ChevronRight className="h-4 w-4 text-[var(--color-fg-tertiary)]" />
        )}
      </button>
      {isOpen && (
        <div className="border-t border-[var(--color-border-subtle)] px-4 py-3">{children}</div>
      )}
    </div>
  );
}

// ─── Transcript Message (Detail View) ───────────────────────

function DetailTranscriptMessage({ turn }: { turn: TranscriptTurn }) {
  const isTutor = turn.speaker === "tutor";

  return (
    <div className={cn("flex gap-3", isTutor ? "justify-start" : "flex-row-reverse")}>
      <div
        className={cn(
          "flex h-7 w-7 shrink-0 items-center justify-center rounded-full",
          isTutor
            ? "bg-[var(--color-info-50)] text-[var(--color-info-500)]"
            : "bg-[var(--color-bg-overlay)] text-[var(--color-fg-tertiary)]",
        )}
      >
        {isTutor ? <GraduationCap className="h-3.5 w-3.5" /> : <User className="h-3.5 w-3.5" />}
      </div>
      <div
        className={cn(
          "max-w-[80%] rounded-2xl px-3 py-2 text-sm leading-relaxed",
          isTutor
            ? "rounded-bl-md border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] text-[var(--color-fg-primary)]"
            : "rounded-br-md bg-[var(--color-info-500)] text-[var(--color-fg-on-accent)]",
        )}
      >
        <p className="whitespace-pre-wrap">{turn.content}</p>
        {turn.bloom_level && isTutor && (
          <div className="mt-1.5">
            <BloomBadge level={turn.bloom_level} />
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Stat Card ──────────────────────────────────────────────

interface StatCardProps {
  label: string;
  value: string | number;
  icon: React.ReactNode;
  subtitle?: string;
}

function StatCard({ label, value, icon, subtitle }: StatCardProps) {
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-3">
      <div className="mb-1 flex items-center gap-1.5 text-[var(--color-fg-tertiary)]">
        {icon}
        <span className="text-[10px] font-medium uppercase tracking-wider">{label}</span>
      </div>
      <div className="text-lg font-bold text-[var(--color-fg-primary)]">{value}</div>
      {subtitle && (
        <div className="mt-0.5 text-[10px] text-[var(--color-fg-tertiary)]">{subtitle}</div>
      )}
    </div>
  );
}

// ─── Tutorial Detail ────────────────────────────────────────

interface TutorialDetailProps {
  tutorial: TutorialDetailType;
}

function TutorialDetailView({ tutorial }: TutorialDetailProps) {
  const analysis = tutorial.analysis;
  const gapsRatio =
    tutorial.knowledge_gaps_found > 0
      ? Math.round((tutorial.knowledge_gaps_addressed / tutorial.knowledge_gaps_found) * 100)
      : null;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <div className="mb-2 flex items-center gap-2">
          <Badge variant="success" size="sm">
            Complete
          </Badge>
          <Badge variant="default" size="sm">
            {tutorial.work_type}
          </Badge>
        </div>
        <h2 className="text-xl font-bold text-[var(--color-fg-primary)]">{tutorial.topic}</h2>
        <div className="mt-2 flex items-center gap-4 text-xs text-[var(--color-fg-tertiary)]">
          <span className="flex items-center gap-1">
            <Clock className="h-3 w-3" />
            {format(parseISO(tutorial.created_at), "MMM d, yyyy")}
          </span>
          {tutorial.completed_at && (
            <span>Completed {format(parseISO(tutorial.completed_at), "MMM d, yyyy")}</span>
          )}
        </div>
      </div>

      {/* Bloom Progression */}
      <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-4">
        <h3 className="mb-3 text-sm font-semibold text-[var(--color-fg-primary)]">
          Bloom Taxonomy Progression
        </h3>
        <BloomIndicator current={tutorial.bloom_end} showLabels />
        {tutorial.bloom_start && tutorial.bloom_end && (
          <div className="mt-3 flex items-center justify-center gap-2 text-xs text-[var(--color-fg-secondary)]">
            <BloomBadge level={tutorial.bloom_start} />
            <span className="text-[var(--color-fg-tertiary)]">to</span>
            <BloomBadge level={tutorial.bloom_end} />
          </div>
        )}
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard
          label="Turns"
          value={tutorial.turn_count}
          icon={<MessageCircle className="h-3 w-3" />}
        />
        <StatCard
          label="Gaps Found"
          value={tutorial.knowledge_gaps_found}
          icon={<Brain className="h-3 w-3" />}
          subtitle={gapsRatio !== null ? `${gapsRatio}% addressed` : undefined}
        />
        <StatCard
          label="Gaps Addressed"
          value={tutorial.knowledge_gaps_addressed}
          icon={<Brain className="h-3 w-3" />}
        />
        <StatCard
          label="Speaking Ratio"
          value={
            tutorial.speaking_ratio_student_pct != null
              ? `${Math.round(tutorial.speaking_ratio_student_pct)}%`
              : "--"
          }
          icon={<Target className="h-3 w-3" />}
          subtitle="Student"
        />
      </div>

      {/* Knowledge Assessment Visualization */}
      {tutorial.knowledge_gaps_found > 0 && (
        <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-4">
          <h3 className="mb-3 text-sm font-semibold text-[var(--color-fg-primary)]">
            Knowledge Assessment
          </h3>
          <div className="flex items-center gap-3">
            <div className="flex-1">
              <div className="mb-1 flex items-center justify-between text-xs">
                <span className="text-[var(--color-fg-secondary)]">Gaps addressed</span>
                <span className="font-medium text-[var(--color-fg-primary)]">
                  {tutorial.knowledge_gaps_addressed} / {tutorial.knowledge_gaps_found}
                </span>
              </div>
              <div className="h-3 w-full overflow-hidden rounded-[var(--radius-full)] bg-[var(--color-bg-overlay)]">
                <div
                  className="h-full rounded-[var(--radius-full)] bg-[var(--color-success-500)] transition-all duration-500"
                  style={{
                    width: `${gapsRatio ?? 0}%`,
                  }}
                />
              </div>
            </div>
          </div>
          {/* Speaking ratio bar */}
          {tutorial.speaking_ratio_student_pct != null && (
            <div className="mt-4">
              <div className="mb-1 flex items-center justify-between text-xs">
                <span className="text-[var(--color-fg-secondary)]">Speaking balance</span>
                <span className="font-medium text-[var(--color-fg-primary)]">
                  Student {Math.round(tutorial.speaking_ratio_student_pct)}% / Tutor{" "}
                  {Math.round(100 - tutorial.speaking_ratio_student_pct)}%
                </span>
              </div>
              <div className="flex h-3 w-full overflow-hidden rounded-[var(--radius-full)]">
                <div
                  className="h-full bg-[var(--color-info-500)] transition-all duration-500"
                  style={{
                    width: `${tutorial.speaking_ratio_student_pct}%`,
                  }}
                />
                <div
                  className="h-full bg-[var(--color-bg-overlay)] transition-all duration-500"
                  style={{
                    width: `${100 - tutorial.speaking_ratio_student_pct}%`,
                  }}
                />
              </div>
              <div className="mt-1 flex items-center justify-between text-[10px] text-[var(--color-fg-tertiary)]">
                <span>Student</span>
                <span>Tutor</span>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Analysis */}
      {analysis && (
        <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-4">
          <h3 className="mb-3 text-sm font-semibold text-[var(--color-fg-primary)]">Analysis</h3>
          {analysis.summary && (
            <p className="mb-3 text-sm text-[var(--color-fg-secondary)]">{analysis.summary}</p>
          )}
          {analysis.bloom_progression && analysis.bloom_progression.length > 0 && (
            <div className="mb-3">
              <h4 className="mb-1.5 text-xs font-medium text-[var(--color-fg-tertiary)]">
                Bloom Level Progression
              </h4>
              <div className="flex flex-wrap gap-1">
                {analysis.bloom_progression.map((level, i) => (
                  <div key={i} className="flex items-center gap-1">
                    <BloomBadge level={level} />
                    {i < analysis.bloom_progression.length - 1 && (
                      <span className="text-[var(--color-fg-disabled)]">{"\u2192"}</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            {analysis.strengths && analysis.strengths.length > 0 && (
              <div>
                <h4 className="mb-1.5 text-xs font-medium text-[var(--color-success-500)]">
                  Strengths
                </h4>
                <ul className="space-y-1 text-xs text-[var(--color-fg-secondary)]">
                  {analysis.strengths.map((s, i) => (
                    <li key={i} className="flex items-start gap-1.5">
                      <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-[var(--color-success-500)]" />
                      {s}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {analysis.areas_for_improvement && analysis.areas_for_improvement.length > 0 && (
              <div>
                <h4 className="mb-1.5 text-xs font-medium text-[var(--color-warning-500)]">
                  Areas for Improvement
                </h4>
                <ul className="space-y-1 text-xs text-[var(--color-fg-secondary)]">
                  {analysis.areas_for_improvement.map((a, i) => (
                    <li key={i} className="flex items-start gap-1.5">
                      <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-[var(--color-warning-500)]" />
                      {a}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Submitted Work */}
      {tutorial.submitted_work && (
        <Collapsible
          title="Submitted Work"
          icon={<FileText className="h-4 w-4 text-[var(--color-fg-tertiary)]" />}
        >
          <div className="whitespace-pre-wrap text-sm text-[var(--color-fg-secondary)]">
            {tutorial.submitted_work}
          </div>
        </Collapsible>
      )}

      {/* Propositions */}
      {tutorial.propositions && tutorial.propositions.length > 0 && (
        <Collapsible
          title={`Propositions (${tutorial.propositions.length})`}
          icon={<Brain className="h-4 w-4 text-[var(--color-fg-tertiary)]" />}
        >
          <ul className="space-y-1.5">
            {tutorial.propositions.map((prop, i) => (
              <li
                key={i}
                className="flex items-start gap-2 text-sm text-[var(--color-fg-secondary)]"
              >
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--color-info-500)]" />
                {prop}
              </li>
            ))}
          </ul>
        </Collapsible>
      )}

      {/* Full Transcript */}
      {tutorial.transcript && tutorial.transcript.length > 0 && (
        <Collapsible
          title={`Full Transcript (${tutorial.transcript.length} messages)`}
          icon={<MessageCircle className="h-4 w-4 text-[var(--color-fg-tertiary)]" />}
          defaultOpen
        >
          <div className="space-y-3">
            {tutorial.transcript.map((turn, i) => (
              <DetailTranscriptMessage key={i} turn={turn} />
            ))}
          </div>
        </Collapsible>
      )}
    </div>
  );
}

export { TutorialDetailView };
export type { TutorialDetailProps };

import { Brain, FileText, User, MapPin } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import type { MemoryAnswer } from "@/types";

function getConfidenceBadge(confidence: number) {
  const pct = Math.round(confidence * 100);
  if (confidence >= 0.8) {
    return { variant: "success" as const, label: `${pct}% confidence` };
  }
  if (confidence >= 0.5) {
    return { variant: "warning" as const, label: `${pct}% confidence` };
  }
  return { variant: "error" as const, label: `${pct}% confidence` };
}

function getSourceSummary(answer: MemoryAnswer): string {
  const counts: Record<string, number> = {};
  for (const source of answer.sources) {
    const key = source.source_type;
    counts[key] = (counts[key] ?? 0) + 1;
  }
  const parts: string[] = [];
  if (counts.episode)
    parts.push(`${counts.episode} diary ${counts.episode === 1 ? "entry" : "entries"}`);
  if (counts.note) parts.push(`${counts.note} ${counts.note === 1 ? "note" : "notes"}`);
  if (counts.entity) parts.push(`${counts.entity} ${counts.entity === 1 ? "entity" : "entities"}`);
  return parts.length > 0 ? `Sources: ${parts.join(", ")}` : "No sources";
}

function getSourceIcon(type: string) {
  switch (type) {
    case "episode":
      return <FileText className="h-3.5 w-3.5" />;
    case "entity":
      return <User className="h-3.5 w-3.5" />;
    case "note":
      return <MapPin className="h-3.5 w-3.5" />;
    default:
      return <FileText className="h-3.5 w-3.5" />;
  }
}

interface AnswerCardProps {
  answer: MemoryAnswer;
  className?: string;
}

export function AnswerCard({ answer, className }: AnswerCardProps) {
  const badge = getConfidenceBadge(answer.confidence);

  return (
    <div
      className={cn(
        "rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] border-l-4 border-l-[var(--color-info-500)]",
        className,
      )}
    >
      <div className="p-5">
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm font-semibold text-[var(--color-fg-primary)]">
            <Brain className="h-4 w-4 text-[var(--color-info-500)]" />
            MEMORY ANSWER
          </div>
          <Badge variant={badge.variant} size="sm">
            {badge.label}
          </Badge>
        </div>

        <div className="prose prose-sm max-w-none text-[var(--color-fg-primary)] [&_a]:text-[var(--color-info-500)] [&_a]:underline [&_strong]:text-[var(--color-fg-primary)] [&_code]:rounded [&_code]:bg-[var(--color-bg-overlay)] [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-[var(--color-fg-secondary)]">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{answer.answer}</ReactMarkdown>
        </div>

        <div className="mt-4 flex items-center gap-4 border-t border-[var(--color-border-subtle)] pt-3">
          <span className="flex items-center gap-1.5 text-xs text-[var(--color-fg-secondary)]">
            {answer.sources.length > 0 && getSourceIcon(answer.sources[0].source_type)}
            {getSourceSummary(answer)}
          </span>
        </div>
      </div>
    </div>
  );
}

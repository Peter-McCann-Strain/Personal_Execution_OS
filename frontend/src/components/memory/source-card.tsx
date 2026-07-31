import { useState, type ReactNode } from "react";
import {
  FileText,
  User,
  Building,
  MapPin,
  Lightbulb,
  ChevronDown,
  ChevronUp,
  ExternalLink,
} from "lucide-react";
import { useNavigate } from "react-router";
import { cn, truncate } from "@/lib/utils";
import type { MemorySearchResult } from "@/types";

const SOURCE_TYPE_CONFIG: Record<string, { label: string; icon: ReactNode; color: string }> = {
  episode: {
    label: "Episode",
    icon: <FileText className="h-3 w-3" />,
    color: "var(--color-agent-diary)",
  },
  note: {
    label: "Note",
    icon: <FileText className="h-3 w-3" />,
    color: "var(--color-info-500)",
  },
  saved_memory: {
    label: "Saved memory",
    icon: <Lightbulb className="h-3 w-3" />,
    color: "var(--color-warning-500)",
  },
  connector_document: {
    label: "Synced connector",
    icon: <Building className="h-3 w-3" />,
    color: "var(--color-agent-comms)",
  },
  entity: {
    label: "Entity",
    icon: <User className="h-3 w-3" />,
    color: "var(--color-success-500)",
  },
};

function getEntityIcon(content: string) {
  const lower = content.toLowerCase();
  if (lower.includes("person")) return <User className="h-3 w-3" />;
  if (lower.includes("org")) return <Building className="h-3 w-3" />;
  if (lower.includes("place")) return <MapPin className="h-3 w-3" />;
  return <Lightbulb className="h-3 w-3" />;
}

function getRelevanceColor(score: number): string {
  if (score >= 0.7) return "var(--color-success-500)";
  if (score >= 0.4) return "var(--color-warning-500)";
  return "var(--color-error-500)";
}

function getNavigationPath(result: MemorySearchResult): string {
  switch (result.source_type) {
    case "episode":
      return `/diary/${result.source_id}`;
    case "note":
      return `/notes/${result.source_id}`;
    case "entity":
      return `/knowledge-graph?entity=${result.source_id}`;
    case "saved_memory":
      return "/memory";
    case "connector_document":
      return "/settings";
    default:
      return "#";
  }
}

function getNavigationLabel(sourceType: string): string {
  switch (sourceType) {
    case "episode":
      return "View full entry";
    case "note":
      return "View note";
    case "entity":
      return "View in Knowledge Graph";
    case "saved_memory":
      return "Open Memory Control Center";
    case "connector_document":
      return "Open connector settings";
    default:
      return "View";
  }
}

interface SourceCardProps {
  result: MemorySearchResult;
  className?: string;
}

export function SourceCard({ result, className }: SourceCardProps) {
  const [expanded, setExpanded] = useState(false);
  const navigate = useNavigate();
  const config = SOURCE_TYPE_CONFIG[result.source_type] ?? SOURCE_TYPE_CONFIG.episode;
  const relevanceColor = getRelevanceColor(result.relevance_score);
  const path = getNavigationPath(result);
  const navLabel = getNavigationLabel(result.source_type);
  const title = result.title?.trim() || null;
  const sourceLabel = result.source_label || config.label;
  const provenanceLabel = result.provenance_label?.trim() || null;
  const isExternal = Boolean(result.source_url);

  const snippetLength = expanded ? result.content.length : 200;
  const displayContent = expanded ? result.content : truncate(result.content, snippetLength);

  return (
    <div
      className={cn(
        "rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] transition-colors hover:border-[var(--color-border-strong)] hover:bg-[var(--color-bg-elevated)]",
        className,
      )}
    >
      <div className="p-4">
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span
              className="inline-flex items-center gap-1 rounded-[var(--radius-full)] px-2 py-0.5 text-[10px] font-medium"
              style={{
                color: config.color,
                borderColor: `color-mix(in oklch, ${config.color} 30%, transparent)`,
                borderStyle: "solid",
                borderWidth: "1px",
              }}
            >
              {result.source_type === "entity" ? getEntityIcon(result.content) : config.icon}
              {sourceLabel}
            </span>
            {provenanceLabel && (
              <span className="text-[11px] text-[var(--color-fg-tertiary)]">{provenanceLabel}</span>
            )}
          </div>

          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1.5">
              <div className="h-1.5 w-24 overflow-hidden rounded-[var(--radius-full)] bg-[var(--color-bg-overlay)]">
                <div
                  className="h-full rounded-[var(--radius-full)] transition-all"
                  style={{
                    width: `${result.relevance_score * 100}%`,
                    backgroundColor: relevanceColor,
                  }}
                />
              </div>
              <span className="text-xs font-mono text-[var(--color-fg-secondary)]">
                {result.relevance_score.toFixed(2)}
              </span>
            </div>
          </div>
        </div>

        {title && (
          <p className="mb-2 text-xs font-medium uppercase tracking-[0.12em] text-[var(--color-fg-tertiary)]">
            {title}
          </p>
        )}
        <p className="text-sm leading-relaxed text-[var(--color-fg-primary)]">{displayContent}</p>

        <div className="mt-3 flex items-center justify-between">
          <button
            type="button"
            onClick={() => {
              if (isExternal && result.source_url) {
                window.open(result.source_url, "_blank", "noopener,noreferrer");
                return;
              }
              navigate(path);
            }}
            className="inline-flex items-center gap-1 text-xs font-medium text-[var(--color-info-500)] transition-colors hover:text-[var(--color-info-600)]"
          >
            {navLabel}
            <ExternalLink className="h-3 w-3" />
          </button>

          {result.content.length > 200 && (
            <button
              type="button"
              onClick={() => setExpanded(!expanded)}
              className="inline-flex items-center gap-1 text-xs text-[var(--color-fg-tertiary)] transition-colors hover:text-[var(--color-fg-secondary)]"
            >
              {expanded ? (
                <>
                  Collapse
                  <ChevronUp className="h-3 w-3" />
                </>
              ) : (
                <>
                  Expand
                  <ChevronDown className="h-3 w-3" />
                </>
              )}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

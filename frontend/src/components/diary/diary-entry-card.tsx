import { useState, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ChevronDown, ChevronUp } from "lucide-react";
import { cn, formatRelativeTime, truncate } from "@/lib/utils";
import { ParaBadge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import type { Episode, EpisodeType, ParaCategory } from "@/types";

// ─── Episode Type Badge ─────────────────────────────────────
const episodeTypeConfig: Record<EpisodeType, { label: string; className: string }> = {
  diary: {
    label: "diary",
    className:
      "bg-[var(--color-agent-research)]/10 text-[var(--color-agent-research)] border-[var(--color-agent-research)]/20",
  },
  capture: {
    label: "capture",
    className:
      "bg-[var(--color-info-50)] text-[var(--color-info-900)] border-[var(--color-info-500)]/20",
  },
  research: {
    label: "research",
    className:
      "bg-[var(--color-agent-research)]/10 text-[var(--color-agent-research)] border-[var(--color-agent-research)]/20",
  },
};

function EpisodeTypeBadge({ type }: { type: EpisodeType }) {
  const config = episodeTypeConfig[type] ?? episodeTypeConfig.diary;
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-[var(--radius-full)] border px-1.5 py-0.5 text-[10px] font-medium leading-tight",
        config.className,
      )}
    >
      {config.label}
    </span>
  );
}

// ─── Mood Indicator ─────────────────────────────────────────
function moodColor(score: number): string {
  if (score <= 2) return "var(--color-error-500)";
  if (score <= 4) return "var(--color-warning-500)";
  if (score <= 6) return "var(--color-warning-500)";
  if (score <= 8) return "var(--color-success-500)";
  return "var(--color-success-500)";
}

function MoodIndicator({ score }: { score: number | null }) {
  if (score == null) {
    return <span className="text-xs text-[var(--color-fg-tertiary)]">Mood --</span>;
  }

  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-[var(--color-fg-secondary)]">
      <span
        className="inline-block h-2 w-2 rounded-full"
        style={{ backgroundColor: moodColor(score) }}
      />
      Mood {score.toFixed(1)}
    </span>
  );
}

// ─── Energy Indicator ───────────────────────────────────────
function energyBarColor(level: number): string {
  if (level <= 3) return "var(--color-error-500)";
  if (level <= 6) return "var(--color-warning-500)";
  return "var(--color-success-500)";
}

function EnergyIndicator({ rating }: { rating: number | null }) {
  if (rating == null) {
    return <span className="text-xs text-[var(--color-fg-tertiary)]">Energy --</span>;
  }

  const segments = 10;
  const filled = Math.round(rating);
  const barCol = energyBarColor(rating);

  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-[var(--color-fg-secondary)]">
      Energy {rating.toFixed(1)}
      <span className="inline-flex gap-px">
        {Array.from({ length: segments }).map((_, i) => (
          <span
            key={i}
            className="inline-block h-2.5 w-[3px] rounded-[1px]"
            style={{
              backgroundColor: i < filled ? barCol : "var(--color-bg-overlay)",
            }}
          />
        ))}
      </span>
    </span>
  );
}

// ─── Tag Chip ───────────────────────────────────────────────
const TAG_COLORS = [
  "oklch(0.7 0.12 30)",
  "oklch(0.7 0.12 60)",
  "oklch(0.7 0.12 90)",
  "oklch(0.7 0.12 120)",
  "oklch(0.7 0.12 150)",
  "oklch(0.7 0.12 180)",
  "oklch(0.7 0.12 210)",
  "oklch(0.7 0.12 240)",
  "oklch(0.7 0.12 270)",
  "oklch(0.7 0.12 300)",
  "oklch(0.7 0.12 330)",
  "oklch(0.7 0.12 0)",
];

function hashTagColor(tag: string): string {
  let hash = 0;
  for (let i = 0; i < tag.length; i++) {
    hash = tag.charCodeAt(i) + ((hash << 5) - hash);
  }
  return TAG_COLORS[Math.abs(hash) % TAG_COLORS.length];
}

function TagChip({ tag, onClick }: { tag: string; onClick?: (tag: string) => void }) {
  const color = hashTagColor(tag);
  return (
    <button
      onClick={() => onClick?.(tag)}
      className="inline-flex items-center rounded-[var(--radius-full)] border border-[var(--color-border-subtle)] bg-[var(--color-bg-overlay)] px-1.5 py-0.5 text-[10px] font-medium transition-colors hover:bg-[var(--color-bg-wash)] cursor-pointer"
      style={{ color }}
    >
      {tag}
    </button>
  );
}

// ─── Main Component ─────────────────────────────────────────
interface DiaryEntryCardProps {
  episode: Episode;
  onTagClick?: (tag: string) => void;
}

export function DiaryEntryCard({ episode, onTagClick }: DiaryEntryCardProps) {
  const [expanded, setExpanded] = useState(false);

  const displayText = useMemo(
    () => episode.summary ?? truncate(episode.content, 120),
    [episode.summary, episode.content],
  );

  return (
    <div
      className={cn(
        "rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] transition-all duration-200",
        "hover:border-[var(--color-border-strong)] hover:shadow-sm",
      )}
    >
      <div className="p-4">
        {/* Top row: badges + timestamp */}
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <EpisodeTypeBadge type={episode.episode_type} />
            {episode.para_category && (
              <ParaBadge category={episode.para_category as ParaCategory} size="sm" />
            )}
          </div>
          <span
            className="text-xs text-[var(--color-fg-tertiary)]"
            title={new Date(episode.created_at).toLocaleString()}
          >
            {formatRelativeTime(episode.created_at)}
          </span>
        </div>

        {/* Summary text */}
        <p className="text-sm text-[var(--color-fg-primary)] line-clamp-2 mb-2">{displayText}</p>

        {/* Expanded content */}
        {expanded && (
          <div className="mb-3 rounded-[var(--radius-md)] bg-[var(--color-bg-elevated)] p-3 text-sm text-[var(--color-fg-primary)] prose prose-sm prose-invert max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{episode.content}</ReactMarkdown>

            {/* Extra metadata */}
            <div className="mt-3 pt-2 border-t border-[var(--color-border-subtle)] flex items-center gap-3 text-xs text-[var(--color-fg-tertiary)]">
              <span>Source: {episode.source}</span>
              <span>ID: {episode.id.slice(0, 8)}</span>
              <span>
                {new Date(episode.created_at).toLocaleString(undefined, {
                  weekday: "short",
                  day: "numeric",
                  month: "short",
                  year: "numeric",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
            </div>
          </div>
        )}

        {/* Mood & Energy */}
        <div className="flex items-center gap-4 mb-2">
          <MoodIndicator score={episode.mood_score} />
          <EnergyIndicator rating={episode.energy_rating} />
        </div>

        {/* Tags + People + Expand */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5 flex-wrap min-w-0">
            {(episode.tags ?? []).slice(0, 5).map((tag) => (
              <TagChip key={tag} tag={tag} onClick={onTagClick} />
            ))}
            {(episode.tags ?? []).length > 5 && (
              <span className="text-[10px] text-[var(--color-fg-tertiary)]">
                +{(episode.tags ?? []).length - 5}
              </span>
            )}

            {(episode.people_mentioned ?? []).length > 0 && (
              <span className="ml-2 text-xs text-[var(--color-fg-tertiary)]">
                {episode.people_mentioned.map((p) => `@${p}`).join(" ")}
              </span>
            )}
          </div>

          <button
            onClick={() => setExpanded(!expanded)}
            className="inline-flex items-center gap-1 text-xs text-[var(--color-fg-secondary)] hover:text-[var(--color-fg-primary)] transition-colors shrink-0 ml-2 cursor-pointer"
          >
            {expanded ? (
              <>
                Collapse <ChevronUp className="h-3 w-3" />
              </>
            ) : (
              <>
                Expand <ChevronDown className="h-3 w-3" />
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Skeleton ───────────────────────────────────────────────
export function DiaryEntryCardSkeleton() {
  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Skeleton className="h-4 w-12" />
          <Skeleton className="h-4 w-14" />
        </div>
        <Skeleton className="h-3 w-16" />
      </div>
      <Skeleton className="h-4 w-full mb-1" />
      <Skeleton className="h-4 w-3/4 mb-3" />
      <div className="flex items-center gap-4 mb-3">
        <Skeleton className="h-3 w-16" />
        <Skeleton className="h-3 w-24" />
      </div>
      <div className="flex items-center gap-1.5">
        <Skeleton className="h-4 w-16" />
        <Skeleton className="h-4 w-20" />
        <Skeleton className="h-4 w-14" />
      </div>
    </div>
  );
}

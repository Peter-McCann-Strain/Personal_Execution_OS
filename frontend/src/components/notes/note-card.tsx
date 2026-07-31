import { memo } from "react";
import { Calendar, ExternalLink } from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge, ParaBadge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { formatRelativeTime, truncate } from "@/lib/utils";
import { noteTypeLabels } from "./note-card.utils";
import type { Note, NoteType } from "@/types";

// ─── Note Type Badge ────────────────────────────────────────

const noteTypeVariantMap: Record<NoteType, "warning" | "info" | "success" | "default"> = {
  fleeting: "warning",
  literature: "info",
  permanent: "success",
  reference: "default",
};

function NoteTypeBadge({ type, size = "sm" }: { type: NoteType; size?: "sm" | "md" }) {
  return (
    <Badge variant={noteTypeVariantMap[type]} size={size}>
      {noteTypeLabels[type]}
    </Badge>
  );
}

// ─── Main Card ──────────────────────────────────────────────

interface NoteCardProps {
  note: Note;
  selected?: boolean;
  onSelect: (note: Note) => void;
}

const NoteCard = memo(function NoteCard({ note, selected = false, onSelect }: NoteCardProps) {
  const contentPreview = truncate(note.content.replace(/[#*_`~>[\]-]/g, ""), 140);

  return (
    <Card
      hoverable
      padding="none"
      className={cn(
        "flex flex-col",
        selected && "ring-2 ring-[var(--color-info-500)] border-[var(--color-info-500)]",
      )}
      onClick={() => onSelect(note)}
    >
      <div className="flex flex-col gap-2 p-4">
        {/* Title */}
        <h3 className="truncate text-sm font-semibold text-[var(--color-fg-primary)]">
          {note.title}
        </h3>

        {/* Content preview */}
        <p className="text-xs leading-relaxed text-[var(--color-fg-secondary)]">
          {contentPreview || "No content"}
        </p>

        {/* Badges */}
        <div className="flex flex-wrap items-center gap-1.5">
          {note.note_type && <NoteTypeBadge type={note.note_type} />}
          {note.para_category && <ParaBadge category={note.para_category} size="sm" />}
          {note.source_url && <ExternalLink className="h-3 w-3 text-[var(--color-fg-tertiary)]" />}
        </div>
      </div>

      {/* Footer: tags + date */}
      <div className="mt-auto flex items-center justify-between border-t border-[var(--color-border-subtle)] px-4 py-2">
        <div className="flex flex-wrap gap-1 overflow-hidden">
          {note.tags.slice(0, 3).map((tag) => (
            <Badge key={tag} size="sm">
              {tag}
            </Badge>
          ))}
          {note.tags.length > 3 && (
            <span className="text-[10px] text-[var(--color-fg-tertiary)]">
              +{note.tags.length - 3}
            </span>
          )}
        </div>
        <span className="flex shrink-0 items-center gap-1 text-[10px] text-[var(--color-fg-tertiary)]">
          <Calendar className="h-3 w-3" />
          {formatRelativeTime(note.created_at)}
        </span>
      </div>
    </Card>
  );
});

export { NoteCard, NoteTypeBadge };
export type { NoteCardProps };

import { useState } from "react";
import type { ReactNode } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link2, Plus, ArrowRight, Loader2, Search, CornerDownLeft, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  createNoteLink,
  getBacklinkedNotes,
  getLinkedNotes,
  getUnlinkedMentions,
  searchNotes,
} from "@/api/notes";
import { NoteTypeBadge } from "./note-card";
import type { LinkedNote } from "@/api/notes";
import type { Note } from "@/types";

// ─── Linked Note Item ───────────────────────────────────────

interface LinkedNoteItemProps {
  linkedNote: LinkedNote;
  onNavigate: (noteId: string) => void;
  actionLabel?: string;
  onAction?: () => void;
  actionBusy?: boolean;
}

function LinkedNoteItem({
  linkedNote,
  onNavigate,
  actionLabel,
  onAction,
  actionBusy,
}: LinkedNoteItemProps) {
  return (
    <div
      className={cn(
        "flex w-full flex-col gap-1.5 rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-3 text-left transition-colors",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={() => onNavigate(linkedNote.id)}
          className="flex min-w-0 flex-1 items-center gap-2 text-left hover:text-[var(--color-info-500)]"
        >
          <h4 className="truncate text-sm font-medium text-[var(--color-fg-primary)]">
            {linkedNote.title}
          </h4>
          <ArrowRight className="h-3.5 w-3.5 shrink-0 text-[var(--color-fg-tertiary)]" />
        </button>
        {actionLabel && onAction ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="gap-1.5"
            loading={actionBusy}
            onClick={onAction}
          >
            <Link2 className="h-3.5 w-3.5" />
            {actionLabel}
          </Button>
        ) : null}
      </div>

      {linkedNote.link_reason && (
        <p className="text-xs text-[var(--color-fg-tertiary)]">{linkedNote.link_reason}</p>
      )}

      <div className="flex items-center gap-2">
        {linkedNote.note_type && <NoteTypeBadge type={linkedNote.note_type} size="sm" />}
        {linkedNote.similarity_score != null && (
          <Badge size="sm" variant="info">
            {Math.round(linkedNote.similarity_score * 100)}% similar
          </Badge>
        )}
      </div>
    </div>
  );
}

// ─── Link Creator ───────────────────────────────────────────

interface LinkCreatorProps {
  noteId: string;
  onCreated: () => void;
  onCancel: () => void;
}

function LinkCreator({ noteId, onCreated, onCancel }: LinkCreatorProps) {
  const queryClient = useQueryClient();
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedNote, setSelectedNote] = useState<Note | null>(null);
  const [linkReason, setLinkReason] = useState("");

  const searchResults = useQuery({
    queryKey: ["notes-search-link", searchQuery],
    queryFn: () => searchNotes(searchQuery, 10),
    enabled: searchQuery.length >= 2,
  });

  const linkMutation = useMutation({
    mutationFn: () =>
      createNoteLink(noteId, {
        target_note_id: selectedNote!.id,
        link_reason: linkReason.trim() || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["note-links", noteId] });
      onCreated();
    },
  });

  const results = (searchResults.data ?? []).filter((n) => n.id !== noteId);

  return (
    <div className="flex flex-col gap-3 rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] p-3">
      <p className="text-xs font-medium text-[var(--color-fg-secondary)]">Link to another note</p>

      {!selectedNote ? (
        <>
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--color-fg-tertiary)]" />
            <Input
              placeholder="Search notes to link..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9"
              autoFocus
            />
          </div>

          {searchResults.isLoading && (
            <div className="flex items-center gap-2 py-2 text-xs text-[var(--color-fg-tertiary)]">
              <Loader2 className="h-3 w-3 animate-spin" />
              Searching...
            </div>
          )}

          {results.length > 0 && (
            <div className="flex max-h-48 flex-col gap-1 overflow-y-auto">
              {results.map((note) => (
                <button
                  key={note.id}
                  onClick={() => setSelectedNote(note)}
                  className="flex items-center gap-2 rounded-[var(--radius-sm)] px-2 py-1.5 text-left text-sm text-[var(--color-fg-secondary)] hover:bg-[var(--color-bg-overlay)] hover:text-[var(--color-fg-primary)] transition-colors cursor-pointer"
                >
                  <Link2 className="h-3.5 w-3.5 shrink-0" />
                  <span className="truncate">{note.title}</span>
                </button>
              ))}
            </div>
          )}

          {searchQuery.length >= 2 && !searchResults.isLoading && results.length === 0 && (
            <p className="py-2 text-center text-xs text-[var(--color-fg-tertiary)]">
              No matching notes found
            </p>
          )}
        </>
      ) : (
        <>
          <div className="flex items-center gap-2 rounded-[var(--radius-sm)] bg-[var(--color-bg-overlay)] px-3 py-2">
            <Link2 className="h-3.5 w-3.5 text-[var(--color-fg-tertiary)]" />
            <span className="flex-1 truncate text-sm text-[var(--color-fg-primary)]">
              {selectedNote.title}
            </span>
            <button
              onClick={() => setSelectedNote(null)}
              className="text-xs text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-primary)] cursor-pointer"
            >
              Change
            </button>
          </div>

          <Input
            placeholder="Reason for linking (optional)..."
            value={linkReason}
            onChange={(e) => setLinkReason(e.target.value)}
          />
        </>
      )}

      {/* Error */}
      {linkMutation.error && (
        <p className="text-xs text-[var(--color-error-500)]">
          {linkMutation.error.message || "Failed to create link"}
        </p>
      )}

      {/* Actions */}
      <div className="flex items-center justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          size="sm"
          className="gap-1.5"
          disabled={!selectedNote}
          loading={linkMutation.isPending}
          onClick={() => linkMutation.mutate()}
        >
          <Link2 className="h-3.5 w-3.5" />
          Create Link
        </Button>
      </div>
    </div>
  );
}

// ─── Main Panel ─────────────────────────────────────────────

interface LinkedNotesPanelProps {
  noteId: string;
  onNavigate: (noteId: string) => void;
}

interface RelationshipSectionProps {
  title: string;
  icon: ReactNode;
  items: LinkedNote[];
  emptyLabel: string;
  onNavigate: (noteId: string) => void;
  actionLabel?: string;
  actionBusyId?: string;
  onAction?: (note: LinkedNote) => void;
}

function RelationshipSection({
  title,
  icon,
  items,
  emptyLabel,
  onNavigate,
  actionLabel,
  actionBusyId,
  onAction,
}: RelationshipSectionProps) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        {icon}
        <h4 className="text-xs font-semibold uppercase tracking-[0.16em] text-[var(--color-fg-tertiary)]">
          {title}
        </h4>
        <Badge size="sm" variant="default">
          {items.length}
        </Badge>
      </div>
      {items.length === 0 ? (
        <p className="rounded-[var(--radius-md)] border border-dashed border-[var(--color-border-default)] px-3 py-2 text-xs text-[var(--color-fg-tertiary)]">
          {emptyLabel}
        </p>
      ) : (
        <div className="flex flex-col gap-2">
          {items.map((item) => (
            <LinkedNoteItem
              key={`${title}-${item.id}`}
              linkedNote={item}
              onNavigate={onNavigate}
              actionLabel={actionLabel}
              actionBusy={actionBusyId === item.id}
              onAction={onAction ? () => onAction(item) : undefined}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function LinkedNotesPanel({ noteId, onNavigate }: LinkedNotesPanelProps) {
  const queryClient = useQueryClient();
  const [showCreator, setShowCreator] = useState(false);

  const linkedNotesQuery = useQuery({
    queryKey: ["note-links", noteId],
    queryFn: () => getLinkedNotes(noteId),
  });
  const backlinksQuery = useQuery({
    queryKey: ["note-backlinks", noteId],
    queryFn: () => getBacklinkedNotes(noteId),
  });
  const unlinkedMentionsQuery = useQuery({
    queryKey: ["note-unlinked-mentions", noteId],
    queryFn: () => getUnlinkedMentions(noteId, 8),
  });

  const convertMentionMutation = useMutation({
    mutationFn: (sourceNoteId: string) =>
      createNoteLink(sourceNoteId, {
        target_note_id: noteId,
        link_reason: "Converted from unlinked mention",
        link_type: "manual",
        origin: "manual",
        auto_discovered: false,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["note-links", noteId] });
      queryClient.invalidateQueries({ queryKey: ["note-backlinks", noteId] });
      queryClient.invalidateQueries({ queryKey: ["note-unlinked-mentions", noteId] });
    },
  });

  const linkedNotes = linkedNotesQuery.data ?? [];
  const backlinks = backlinksQuery.data ?? [];
  const backlinkedIds = new Set(backlinks.map((item) => item.id));
  const outgoingLinks = linkedNotes.filter((item) => !backlinkedIds.has(item.id));
  const unlinkedMentions = unlinkedMentionsQuery.data ?? [];
  const isLoadingAny =
    linkedNotesQuery.isLoading || backlinksQuery.isLoading || unlinkedMentionsQuery.isLoading;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-[var(--color-fg-primary)]">
          <Link2 className="h-4 w-4" />
          Note Relationships
          {(linkedNotes.length > 0 || backlinks.length > 0 || unlinkedMentions.length > 0) && (
            <span className="text-xs font-normal text-[var(--color-fg-tertiary)]">
              ({linkedNotes.length + backlinks.length + unlinkedMentions.length})
            </span>
          )}
        </h3>
        {!showCreator && (
          <Button
            variant="ghost"
            size="sm"
            className="gap-1.5"
            onClick={() => setShowCreator(true)}
          >
            <Plus className="h-3.5 w-3.5" />
            Link
          </Button>
        )}
      </div>

      {/* Link creator */}
      {showCreator && (
        <LinkCreator
          noteId={noteId}
          onCreated={() => setShowCreator(false)}
          onCancel={() => setShowCreator(false)}
        />
      )}

      {/* Loading */}
      {isLoadingAny && (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      )}

      {!isLoadingAny &&
        linkedNotes.length === 0 &&
        backlinks.length === 0 &&
        unlinkedMentions.length === 0 &&
        !showCreator && (
          <p className="py-4 text-center text-xs text-[var(--color-fg-tertiary)]">
            No relationships discovered yet
          </p>
        )}

      {!isLoadingAny &&
        (outgoingLinks.length > 0 || backlinks.length > 0 || unlinkedMentions.length > 0) && (
          <div className="grid gap-4 lg:grid-cols-3">
            <RelationshipSection
              title="Outgoing Links"
              icon={<ArrowRight className="h-4 w-4 text-[var(--color-fg-tertiary)]" />}
              items={outgoingLinks}
              emptyLabel="No explicit outgoing links from this note yet."
              onNavigate={onNavigate}
            />
            <RelationshipSection
              title="Backlinks"
              icon={<CornerDownLeft className="h-4 w-4 text-[var(--color-fg-tertiary)]" />}
              items={backlinks}
              emptyLabel="No notes explicitly link back here yet."
              onNavigate={onNavigate}
            />
            <RelationshipSection
              title="Unlinked Mentions"
              icon={<Sparkles className="h-4 w-4 text-[var(--color-warning-500)]" />}
              items={unlinkedMentions}
              emptyLabel="No strong unlinked mentions detected."
              onNavigate={onNavigate}
              actionLabel="Convert"
              actionBusyId={
                convertMentionMutation.isPending ? convertMentionMutation.variables : undefined
              }
              onAction={(item) => convertMentionMutation.mutate(item.id)}
            />
          </div>
        )}
    </div>
  );
}

export { LinkedNotesPanel };
export type { LinkedNotesPanelProps };

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ChevronLeft,
  Edit3,
  Mic2,
  Trash2,
  Calendar,
  ExternalLink,
  Clock,
  Network,
  Shapes,
} from "lucide-react";
import { Badge, ParaBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { NoteTypeBadge } from "./note-card";
import { NoteEditor } from "./note-editor";
import { LinkedNotesPanel } from "./linked-notes-panel";
import { deleteNote, getNote, getNoteGraph } from "@/api/notes";
import { createContentAsset } from "@/api/content-assets";

// ─── Helpers ────────────────────────────────────────────────

function formatDate(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleDateString("en-GB", {
    weekday: "short",
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// ─── Component ──────────────────────────────────────────────

interface NoteDetailProps {
  noteId: string;
  onBack: () => void;
  onNavigateNote: (noteId: string) => void;
}

function NoteDetail({ noteId, onBack, onNavigateNote }: NoteDetailProps) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const noteQuery = useQuery({
    queryKey: ["note", noteId],
    queryFn: () => getNote(noteId),
  });
  const localGraphQuery = useQuery({
    queryKey: ["note-local-graph", noteId],
    queryFn: () => getNoteGraph({ note_id: noteId, depth: 1, limit: 24 }),
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteNote(noteId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notes"] });
      onBack();
    },
  });

  const contentAssetMutation = useMutation({
    mutationFn: () =>
      createContentAsset({
        note_id: noteId,
        asset_type: "notebooklm_podcast",
        status: "ready",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["content-assets"] });
    },
  });

  const note = noteQuery.data;
  const localGraph = localGraphQuery.data;
  const localNeighbors = (localGraph?.nodes ?? []).filter((item) => item.id !== noteId);
  const edgeTypes = Array.from(new Set((localGraph?.edges ?? []).map((edge) => edge.link_type)));

  // ─── Loading ──────────────────────────────────────────
  if (noteQuery.isLoading) {
    return (
      <div className="flex flex-col gap-4 p-6">
        <Skeleton className="h-8 w-32" />
        <Skeleton className="h-12 w-3/4" />
        <Skeleton className="h-64 w-full" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  // ─── Not Found ────────────────────────────────────────
  if (!note) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 p-12 text-[var(--color-fg-tertiary)]">
        <p>Note not found</p>
        <Button variant="ghost" onClick={onBack}>
          Go back
        </Button>
      </div>
    );
  }

  const aliases = note.aliases ?? [];

  // ─── Editor Modal ─────────────────────────────────────
  if (editing) {
    return (
      <NoteEditor
        note={note}
        onClose={() => setEditing(false)}
        onSaved={() => {
          setEditing(false);
          noteQuery.refetch();
        }}
      />
    );
  }

  return (
    <div className="mx-auto flex max-w-[900px] flex-col gap-6 p-6">
      {/* Back button */}
      <Button variant="ghost" size="sm" className="w-fit gap-1.5" onClick={onBack}>
        <ChevronLeft className="h-4 w-4" />
        Back to notes
      </Button>

      {/* Main content card */}
      <Card padding="lg">
        {/* Header */}
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 flex-1">
            <h1 className="text-lg font-semibold text-[var(--color-fg-primary)]">{note.title}</h1>

            {/* Badges */}
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {note.note_type && <NoteTypeBadge type={note.note_type} size="md" />}
              {note.para_category && <ParaBadge category={note.para_category} size="md" />}
            </div>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              className="gap-1.5"
              loading={contentAssetMutation.isPending}
              onClick={() => contentAssetMutation.mutate()}
            >
              <Mic2 className="h-3.5 w-3.5" />
              Queue Podcast
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="gap-1.5"
              onClick={() => setEditing(true)}
            >
              <Edit3 className="h-3.5 w-3.5" />
              Edit
            </Button>
            {!confirmDelete ? (
              <Button
                variant="ghost"
                size="sm"
                className="gap-1.5 text-[var(--color-error-500)]"
                onClick={() => setConfirmDelete(true)}
              >
                <Trash2 className="h-3.5 w-3.5" />
                Delete
              </Button>
            ) : (
              <div className="flex items-center gap-1.5">
                <Button
                  variant="destructive"
                  size="sm"
                  loading={deleteMutation.isPending}
                  onClick={() => deleteMutation.mutate()}
                >
                  Confirm
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(false)}>
                  Cancel
                </Button>
              </div>
            )}
          </div>
        </div>

        {/* Metadata */}
        <div className="mt-4 flex flex-wrap items-center gap-4 text-xs text-[var(--color-fg-tertiary)]">
          <span className="flex items-center gap-1">
            <Calendar className="h-3.5 w-3.5" />
            Created: {formatDate(note.created_at)}
          </span>
          <span className="flex items-center gap-1">
            <Clock className="h-3.5 w-3.5" />
            Updated: {formatDate(note.updated_at)}
          </span>
          {note.source_url && (
            <a
              href={note.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 text-[var(--color-info-500)] hover:underline"
            >
              <ExternalLink className="h-3.5 w-3.5" />
              Source
            </a>
          )}
        </div>

        {/* Tags */}
        {note.tags.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-1.5">
            {note.tags.map((tag) => (
              <Badge key={tag}>{tag}</Badge>
            ))}
          </div>
        )}

        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <div className="rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] p-3">
            <div className="mb-2 flex items-center gap-2">
              <Shapes className="h-4 w-4 text-[var(--color-fg-tertiary)]" />
              <h3 className="text-xs font-semibold uppercase tracking-[0.16em] text-[var(--color-fg-tertiary)]">
                Properties
              </h3>
            </div>
            <div className="space-y-2 text-xs text-[var(--color-fg-secondary)]">
              <p>
                <span className="font-medium text-[var(--color-fg-primary)]">Slug:</span>{" "}
                {note.slug ?? "auto"}
              </p>
              <p>
                <span className="font-medium text-[var(--color-fg-primary)]">Kind:</span>{" "}
                {note.kind ?? "note"}
              </p>
              <p>
                <span className="font-medium text-[var(--color-fg-primary)]">Aliases:</span>{" "}
                {aliases.length > 0 ? aliases.join(", ") : "None"}
              </p>
            </div>
          </div>

          <div className="rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] p-3">
            <div className="mb-2 flex items-center gap-2">
              <Network className="h-4 w-4 text-[var(--color-fg-tertiary)]" />
              <h3 className="text-xs font-semibold uppercase tracking-[0.16em] text-[var(--color-fg-tertiary)]">
                Local Graph
              </h3>
            </div>
            <div className="space-y-2">
              <p className="text-xs text-[var(--color-fg-secondary)]">
                {(localGraph?.nodes.length ?? 1) - 1} nearby notes · {localGraph?.edges.length ?? 0}{" "}
                visible links
              </p>
              <div className="flex flex-wrap gap-1.5">
                {edgeTypes.length > 0 ? (
                  edgeTypes.map((edgeType) => (
                    <Badge key={edgeType} size="sm" variant="default">
                      {edgeType}
                    </Badge>
                  ))
                ) : (
                  <span className="text-xs text-[var(--color-fg-tertiary)]">
                    No linked neighbors yet
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Divider */}
        <div className="my-6 border-t border-[var(--color-border-subtle)]" />

        {/* Content — rendered as markdown */}
        <div className="prose-custom">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{note.content}</ReactMarkdown>
        </div>

        {/* Executive summary (if available) */}
        {note.executive_summary && (
          <>
            <div className="my-6 border-t border-[var(--color-border-subtle)]" />
            <div>
              <h3 className="mb-2 text-sm font-semibold text-[var(--color-fg-primary)]">
                Executive Summary
              </h3>
              <p className="text-sm leading-relaxed text-[var(--color-fg-secondary)]">
                {note.executive_summary}
              </p>
            </div>
          </>
        )}

        {Object.keys(note.frontmatter).length > 0 && (
          <>
            <div className="my-6 border-t border-[var(--color-border-subtle)]" />
            <div>
              <h3 className="mb-2 text-sm font-semibold text-[var(--color-fg-primary)]">
                Frontmatter
              </h3>
              <pre className="overflow-x-auto rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] p-3 text-xs text-[var(--color-fg-secondary)]">
                {JSON.stringify(note.frontmatter, null, 2)}
              </pre>
            </div>
          </>
        )}
      </Card>

      {/* Linked notes */}
      <Card padding="lg">
        <LinkedNotesPanel noteId={noteId} onNavigate={onNavigateNote} />
      </Card>

      <Card padding="lg" className="gap-3">
        <div>
          <h3 className="text-sm font-semibold text-[var(--color-fg-primary)]">
            Local Graph Neighbors
          </h3>
          <p className="mt-1 text-xs text-[var(--color-fg-tertiary)]">
            The one-hop neighborhood around this note.
          </p>
        </div>
        {localGraphQuery.isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : localNeighbors.length === 0 ? (
          <p className="text-sm text-[var(--color-fg-tertiary)]">
            No neighboring notes discovered yet.
          </p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {localNeighbors.map((neighbor) => (
              <Button
                key={neighbor.id}
                type="button"
                size="sm"
                variant="outline"
                className="justify-start"
                onClick={() => onNavigateNote(neighbor.id)}
              >
                {neighbor.title}
              </Button>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

export { NoteDetail };
export type { NoteDetailProps };

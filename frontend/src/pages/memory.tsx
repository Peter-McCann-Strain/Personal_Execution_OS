import { useCallback, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  Brain,
  CheckCircle2,
  Edit3,
  Layers3,
  Pin,
  Plus,
  Search as SearchIcon,
  Trash2,
} from "lucide-react";
import { SearchInput } from "@/components/memory/search-input";
import { AnswerCard } from "@/components/memory/answer-card";
import { SourceCard } from "@/components/memory/source-card";
import { FollowUpPills } from "@/components/memory/follow-up-pills";
import { Skeleton } from "@/components/ui/skeleton";
import { PageError } from "@/components/ui/page-error";
import { PageTransition } from "@/components/ui/page-transition";
import { searchMemory } from "@/api/memory";
import {
  createSavedMemory,
  deleteSavedMemory,
  listSavedMemories,
  mergeSavedMemories,
  updateSavedMemory,
} from "@/api/saved-memories";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { MemoryAnswer, SavedMemory } from "@/types";

function SearchSkeleton() {
  return (
    <div className="w-full max-w-2xl space-y-4">
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-20 w-full" />
      <Skeleton className="h-20 w-full" />
      <Skeleton className="h-20 w-3/4" />
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center gap-4 pt-12 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-[var(--radius-full)] bg-[var(--color-bg-overlay)]">
        <Brain className="h-8 w-8 text-[var(--color-fg-tertiary)]" />
      </div>
      <div className="space-y-2">
        <h2 className="text-lg font-semibold text-[var(--color-fg-primary)]">
          Ask me anything about your notes, diary, or knowledge base.
        </h2>
        <p className="max-w-md text-sm text-[var(--color-fg-secondary)]">
          Search across all your stored knowledge using hybrid BM25 + vector search.
        </p>
      </div>
      <div className="flex flex-col items-center gap-1.5 pt-2">
        <span className="text-xs text-[var(--color-fg-tertiary)]">Try:</span>
        {[
          "When did I last discuss the project?",
          "What do I know about RAG evaluation?",
          "Summarize my meetings this week",
        ].map((q) => (
          <span key={q} className="text-sm text-[var(--color-fg-secondary)]">
            "{q}"
          </span>
        ))}
      </div>
    </div>
  );
}

function NoResultsState({ query }: { query: string }) {
  return (
    <div className="flex flex-col items-center gap-4 pt-8 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-[var(--radius-full)] bg-[var(--color-bg-overlay)]">
        <SearchIcon className="h-8 w-8 text-[var(--color-fg-tertiary)]" />
      </div>
      <div className="space-y-2">
        <h2 className="text-base font-semibold text-[var(--color-fg-primary)]">
          Nothing found for "{query}"
        </h2>
        <p className="max-w-md text-sm text-[var(--color-fg-secondary)]">
          Try rephrasing your question, or capture this as a new note so you can find it later.
        </p>
      </div>
    </div>
  );
}

export function MemoryPage() {
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [lastQuery, setLastQuery] = useState("");
  const [answer, setAnswer] = useState<MemoryAnswer | null>(null);
  const [memoryTitle, setMemoryTitle] = useState("");
  const [memoryContent, setMemoryContent] = useState("");
  const [sensitiveMode, setSensitiveMode] = useState(false);
  const [suppressedSources, setSuppressedSources] = useState<string[]>([]);
  const [selectedMemoryIds, setSelectedMemoryIds] = useState<string[]>([]);

  const mutation = useMutation({
    mutationFn: searchMemory,
    onSuccess: (data) => {
      setAnswer(data);
    },
  });
  const savedMemoriesQuery = useQuery({
    queryKey: ["saved-memories", "memory-page"],
    queryFn: () => listSavedMemories({ limit: 12 }),
  });

  const createMemoryMutation = useMutation({
    mutationFn: () =>
      createSavedMemory({
        title: memoryTitle,
        content: memoryContent,
        scope: "global",
        source_type: "manual",
      }),
    onSuccess: () => {
      setMemoryTitle("");
      setMemoryContent("");
      queryClient.invalidateQueries({ queryKey: ["saved-memories"] });
    },
  });

  const updateMemoryMutation = useMutation({
    mutationFn: ({ memoryId, data }: { memoryId: string; data: Record<string, unknown> }) =>
      updateSavedMemory(memoryId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["saved-memories"] });
    },
  });

  const deleteMemoryMutation = useMutation({
    mutationFn: (memoryId: string) => deleteSavedMemory(memoryId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["saved-memories"] });
    },
  });
  const mergeMemoryMutation = useMutation({
    mutationFn: () =>
      mergeSavedMemories({
        target_memory_id: selectedMemoryIds[0]!,
        source_memory_ids: selectedMemoryIds.slice(1),
      }),
    onSuccess: () => {
      setSelectedMemoryIds([]);
      queryClient.invalidateQueries({ queryKey: ["saved-memories"] });
    },
  });

  const handleSearch = useCallback(() => {
    if (!query.trim()) return;
    setLastQuery(query.trim());
    mutation.mutate({
      query: query.trim(),
      sensitive_mode: sensitiveMode,
      suppressed_sources: suppressedSources,
    });
  }, [mutation, query, sensitiveMode, suppressedSources]);

  const handleFollowUp = useCallback(
    (suggestion: string) => {
      setQuery(suggestion);
      setLastQuery(suggestion);
      mutation.mutate({
        query: suggestion,
        sensitive_mode: sensitiveMode,
        suppressed_sources: suppressedSources,
      });
    },
    [mutation, sensitiveMode, suppressedSources],
  );

  const hasSearched = lastQuery.length > 0;
  const hasResults = answer !== null && answer.sources.length > 0;
  const noResults =
    hasSearched && !mutation.isPending && answer !== null && answer.sources.length === 0;
  const savedMemories = savedMemoriesQuery.data?.items ?? [];
  const selectedCount = selectedMemoryIds.length;
  const sourceFilters = [
    { key: "saved_memory", label: "Saved memories" },
    { key: "connector_document", label: "Connector data" },
    { key: "note", label: "Notes" },
    { key: "episode", label: "Recent chat" },
  ];

  return (
    <PageTransition>
      <div className="flex flex-col items-center px-4 py-8">
        <h1 className="mb-8 text-2xl font-semibold text-[var(--color-fg-primary)]">
          Memory Search
        </h1>

        <SearchInput
          value={query}
          onChange={setQuery}
          onSubmit={handleSearch}
          loading={mutation.isPending}
        />

        <div className="mt-4 flex w-full max-w-2xl flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant={sensitiveMode ? "default" : "outline"}
            onClick={() => setSensitiveMode((prev) => !prev)}
          >
            {sensitiveMode ? "Sensitive mode on" : "Sensitive mode"}
          </Button>
          {sourceFilters.map((filter) => {
            const suppressed = suppressedSources.includes(filter.key);
            return (
              <Button
                key={filter.key}
                size="sm"
                variant={suppressed ? "outline" : "default"}
                onClick={() =>
                  setSuppressedSources((current) =>
                    current.includes(filter.key)
                      ? current.filter((item) => item !== filter.key)
                      : [...current, filter.key],
                  )
                }
              >
                {suppressed ? `Show ${filter.label}` : filter.label}
              </Button>
            );
          })}
        </div>
        <p className="mt-2 w-full max-w-2xl text-xs text-[var(--color-fg-tertiary)]">
          Sensitive mode temporarily suppresses saved memories and synced connector data.
        </p>

        <div className="mt-8 w-full max-w-2xl space-y-4">
          {mutation.isPending && <SearchSkeleton />}

          {!mutation.isPending && !hasSearched && <EmptyState />}

          {!mutation.isPending && noResults && <NoResultsState query={lastQuery} />}

          {!mutation.isPending && hasResults && answer && (
            <>
              <AnswerCard answer={answer} />

              <div className="space-y-3">
                {answer.sources.map((source) => (
                  <SourceCard key={`${source.source_type}-${source.source_id}`} result={source} />
                ))}
              </div>

              {answer.follow_up_suggestions.length > 0 && (
                <FollowUpPills
                  suggestions={answer.follow_up_suggestions}
                  onSelect={handleFollowUp}
                />
              )}
            </>
          )}

          {mutation.isError && (
            <PageError
              message={
                mutation.error instanceof Error
                  ? mutation.error.message
                  : "Memory search failed with an unknown error."
              }
              onRetry={() => {
                if (lastQuery) {
                  mutation.mutate({
                    query: lastQuery,
                    sensitive_mode: sensitiveMode,
                    suppressed_sources: suppressedSources,
                  });
                }
              }}
            />
          )}
        </div>

        <div className="mt-10 w-full max-w-4xl space-y-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-[var(--color-fg-primary)]">
                Memory Control Center
              </h2>
              <p className="text-sm text-[var(--color-fg-secondary)]">
                Inspect, edit, merge, pin, snooze, archive, and forget your explicit saved memories.
              </p>
            </div>
            <div className="flex items-center gap-2">
              {selectedCount > 0 ? (
                <Badge size="sm" variant="info">
                  {selectedCount} selected
                </Badge>
              ) : null}
              <Badge size="sm">{savedMemories.length} memories</Badge>
            </div>
          </div>

          {selectedCount > 0 ? (
            <Card padding="lg" className="gap-3">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h3 className="text-sm font-semibold text-[var(--color-fg-primary)]">
                    Merge selection
                  </h3>
                  <p className="mt-1 text-sm text-[var(--color-fg-secondary)]">
                    The first selected memory stays. The rest merge into it and are archived from
                    the active set.
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button variant="outline" onClick={() => setSelectedMemoryIds([])}>
                    Clear
                  </Button>
                  <Button
                    loading={mergeMemoryMutation.isPending}
                    disabled={selectedCount < 2}
                    onClick={() => mergeMemoryMutation.mutate()}
                  >
                    <Layers3 className="h-4 w-4" />
                    Merge selected
                  </Button>
                </div>
              </div>
            </Card>
          ) : null}

          <Card padding="lg" className="gap-3">
            <div>
              <h3 className="text-sm font-semibold text-[var(--color-fg-primary)]">
                Save explicit memory
              </h3>
              <p className="mt-1 text-sm text-[var(--color-fg-secondary)]">
                Pin stable facts or preferences separate from notes and chat history.
              </p>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <input
                value={memoryTitle}
                onChange={(event) => setMemoryTitle(event.target.value)}
                className="h-10 rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] px-3 text-sm text-[var(--color-fg-primary)]"
                placeholder="Prefers concise weekly summaries"
              />
              <Button
                loading={createMemoryMutation.isPending}
                disabled={!memoryTitle.trim() || !memoryContent.trim()}
                onClick={() => createMemoryMutation.mutate()}
              >
                <Plus className="h-4 w-4" />
                Save memory
              </Button>
            </div>
            <textarea
              value={memoryContent}
              onChange={(event) => setMemoryContent(event.target.value)}
              rows={3}
              className="w-full rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] px-3 py-2 text-sm text-[var(--color-fg-primary)]"
              placeholder="Use short executive summaries unless I ask for detail."
            />
          </Card>

          <div className="grid gap-3 md:grid-cols-2">
            {savedMemories.map((memory) => (
              <SavedMemoryCard
                key={`${memory.id}:${memory.updated_at}`}
                memory={memory}
                onPin={() =>
                  updateMemoryMutation.mutate({
                    memoryId: memory.id,
                    data: { pinned: !memory.pinned },
                  })
                }
                onSnooze={() =>
                  updateMemoryMutation.mutate({
                    memoryId: memory.id,
                    data: { state: memory.state === "snoozed" ? "active" : "snoozed" },
                  })
                }
                onArchive={() =>
                  updateMemoryMutation.mutate({
                    memoryId: memory.id,
                    data: { state: memory.state === "archived" ? "active" : "archived" },
                  })
                }
                onConfirm={() =>
                  updateMemoryMutation.mutate({
                    memoryId: memory.id,
                    data: { confirm_now: true },
                  })
                }
                onEdit={(data) =>
                  updateMemoryMutation.mutate({
                    memoryId: memory.id,
                    data,
                  })
                }
                onMarkUsed={() =>
                  updateMemoryMutation.mutate({
                    memoryId: memory.id,
                    data: { mark_used: true },
                  })
                }
                onDelete={() => deleteMemoryMutation.mutate(memory.id)}
                selected={selectedMemoryIds.includes(memory.id)}
                onToggleSelect={() =>
                  setSelectedMemoryIds((current) =>
                    current.includes(memory.id)
                      ? current.filter((item) => item !== memory.id)
                      : [...current, memory.id],
                  )
                }
                busy={updateMemoryMutation.isPending || deleteMemoryMutation.isPending}
              />
            ))}
          </div>
        </div>
      </div>
    </PageTransition>
  );
}

function SavedMemoryCard({
  memory,
  onPin,
  onSnooze,
  onArchive,
  onConfirm,
  onEdit,
  onMarkUsed,
  onDelete,
  selected,
  onToggleSelect,
  busy,
}: {
  memory: SavedMemory;
  onPin: () => void;
  onSnooze: () => void;
  onArchive: () => void;
  onConfirm: () => void;
  onEdit: (data: { title: string; content: string; scope: SavedMemory["scope"] }) => void;
  onMarkUsed: () => void;
  onDelete: () => void;
  selected: boolean;
  onToggleSelect: () => void;
  busy: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draftTitle, setDraftTitle] = useState(memory.title);
  const [draftContent, setDraftContent] = useState(memory.content);
  const [draftScope, setDraftScope] = useState<SavedMemory["scope"]>(memory.scope);

  return (
    <Card padding="lg" className="gap-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          {editing ? (
            <div className="space-y-2">
              <input
                aria-label="Memory title"
                value={draftTitle}
                onChange={(event) => setDraftTitle(event.target.value)}
                className="h-10 w-full rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] px-3 text-sm text-[var(--color-fg-primary)]"
              />
              <select
                aria-label="Memory scope"
                value={draftScope}
                onChange={(event) => setDraftScope(event.target.value as SavedMemory["scope"])}
                className="h-9 w-full rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] px-3 text-sm text-[var(--color-fg-primary)]"
              >
                <option value="global">Global</option>
                <option value="person">Person</option>
                <option value="project">Project</option>
              </select>
            </div>
          ) : (
            <>
              <h3 className="text-sm font-semibold text-[var(--color-fg-primary)]">
                {memory.title}
              </h3>
              <p className="mt-1 text-xs text-[var(--color-fg-tertiary)]">
                {memory.scope} · {memory.state}
              </p>
            </>
          )}
        </div>
        <div className="flex items-center gap-2">
          {selected ? (
            <Badge size="sm" variant="info">
              Selected
            </Badge>
          ) : null}
          {memory.pinned && <Badge size="sm">Pinned</Badge>}
        </div>
      </div>
      {editing ? (
        <textarea
          value={draftContent}
          onChange={(event) => setDraftContent(event.target.value)}
          rows={4}
          className="w-full rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] px-3 py-2 text-sm text-[var(--color-fg-primary)]"
        />
      ) : (
        <p className="text-sm text-[var(--color-fg-secondary)]">{memory.content}</p>
      )}
      <div className="flex flex-wrap gap-2 text-xs text-[var(--color-fg-tertiary)]">
        {memory.last_confirmed_at ? (
          <span>confirmed {new Date(memory.last_confirmed_at).toLocaleDateString("en-GB")}</span>
        ) : (
          <span>not confirmed yet</span>
        )}
        {memory.last_used_at ? (
          <span>used {new Date(memory.last_used_at).toLocaleDateString("en-GB")}</span>
        ) : null}
        {memory.source_type && <span>source: {memory.source_type}</span>}
        {typeof memory.provenance?.created_via === "string" && (
          <span>why remembered: {memory.provenance.created_via}</span>
        )}
        {Array.isArray(memory.provenance?.merged_from_titles) &&
        memory.provenance.merged_from_titles.length > 0 ? (
          <span>merged: {memory.provenance.merged_from_titles.length}</span>
        ) : null}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant={selected ? "default" : "outline"}
          disabled={busy}
          onClick={onToggleSelect}
        >
          <Layers3 className="h-4 w-4" />
          {selected ? "Selected" : "Select"}
        </Button>
        {editing ? (
          <>
            <Button
              size="sm"
              variant="outline"
              disabled={busy || !draftTitle.trim() || !draftContent.trim()}
              onClick={() => {
                onEdit({
                  title: draftTitle.trim(),
                  content: draftContent.trim(),
                  scope: draftScope,
                });
                setEditing(false);
              }}
            >
              <CheckCircle2 className="h-4 w-4" />
              Save edit
            </Button>
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </>
        ) : (
          <Button size="sm" variant="outline" disabled={busy} onClick={() => setEditing(true)}>
            <Edit3 className="h-4 w-4" />
            Edit
          </Button>
        )}
        <Button size="sm" variant="outline" disabled={busy} onClick={onPin}>
          <Pin className="h-4 w-4" />
          {memory.pinned ? "Unpin" : "Pin"}
        </Button>
        <Button size="sm" variant="outline" disabled={busy} onClick={onMarkUsed}>
          <Brain className="h-4 w-4" />
          Mark used
        </Button>
        <Button size="sm" variant="outline" disabled={busy} onClick={onSnooze}>
          <Brain className="h-4 w-4" />
          {memory.state === "snoozed" ? "Unsnooze" : "Snooze"}
        </Button>
        <Button size="sm" variant="outline" disabled={busy} onClick={onArchive}>
          <Archive className="h-4 w-4" />
          {memory.state === "archived" ? "Restore" : "Archive"}
        </Button>
        <Button size="sm" variant="outline" disabled={busy} onClick={onConfirm}>
          <CheckCircle2 className="h-4 w-4" />
          Confirm
        </Button>
        <Button size="sm" variant="outline" disabled={busy} onClick={onDelete}>
          <Trash2 className="h-4 w-4" />
          Forget
        </Button>
      </div>
    </Card>
  );
}

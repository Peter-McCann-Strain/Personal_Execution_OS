import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as Tabs from "@radix-ui/react-tabs";
import {
  BookOpen,
  Download,
  Network,
  NotebookTabs,
  PanelsTopLeft,
  Plus,
  Radio,
  Search,
  StickyNote,
  Upload,
  X,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { PageError } from "@/components/ui/page-error";
import { PageHeader } from "@/components/ui/page-header";
import { PageTransition } from "@/components/ui/page-transition";
import { Skeleton } from "@/components/ui/skeleton";
import { SortMenu } from "@/components/ui/sort-menu";
import { Input } from "@/components/ui/input";
import { NoteCard } from "@/components/notes/note-card";
import { NoteDetail } from "@/components/notes/note-detail";
import { NoteEditor } from "@/components/notes/note-editor";
import { cn } from "@/lib/utils";
import {
  createNoteCanvas,
  listNoteCanvases,
  listNotes,
  getNoteGraph,
  upsertDailyNote,
} from "@/api/notes";
import {
  generateContentAssetSourcePack,
  getContentAssets,
  updateContentAsset,
} from "@/api/content-assets";
import { useDebounce } from "@/hooks/use-debounce";
import type {
  ContentAsset,
  Note,
  NoteCanvas,
  NoteGraph,
  NoteKind,
  NoteType,
  ParaCategory,
} from "@/types";

type SortOption = "newest" | "oldest" | "title_asc" | "title_desc";
type NotesTab = "all" | "graph" | "daily" | "moc" | "canvases" | "content";

const tabs: Array<{ value: NotesTab; label: string }> = [
  { value: "all", label: "All" },
  { value: "graph", label: "Graph" },
  { value: "daily", label: "Daily" },
  { value: "moc", label: "MOCs" },
  { value: "canvases", label: "Canvases" },
  { value: "content", label: "Content" },
];

const sortOptions: { value: SortOption; label: string }[] = [
  { value: "newest", label: "Newest first" },
  { value: "oldest", label: "Oldest first" },
  { value: "title_asc", label: "Title A-Z" },
  { value: "title_desc", label: "Title Z-A" },
];

const noteTypeOptions: { value: NoteType; label: string }[] = [
  { value: "fleeting", label: "Fleeting" },
  { value: "literature", label: "Literature" },
  { value: "permanent", label: "Permanent" },
  { value: "reference", label: "Reference" },
];

const paraCategoryOptions: { value: ParaCategory; label: string }[] = [
  { value: "project", label: "Project" },
  { value: "area", label: "Area" },
  { value: "resource", label: "Resource" },
  { value: "archive", label: "Archive" },
];

function sortNotes(notes: Note[], sort: SortOption): Note[] {
  const sorted = [...notes];
  switch (sort) {
    case "newest":
      return sorted.sort(
        (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
      );
    case "oldest":
      return sorted.sort(
        (a, b) => new Date(a.updated_at).getTime() - new Date(b.updated_at).getTime(),
      );
    case "title_asc":
      return sorted.sort((a, b) => a.title.localeCompare(b.title));
    case "title_desc":
      return sorted.sort((a, b) => b.title.localeCompare(a.title));
  }
}

function todayIsoDate(): string {
  return new Date().toISOString().slice(0, 10);
}

function GraphPanel({
  notes,
  graph,
  selectedNoteId,
  onSelectNote,
  onOpenNote,
  kindFilter,
  onKindFilterChange,
}: {
  notes: Note[];
  graph: NoteGraph | undefined;
  selectedNoteId: string | null;
  onSelectNote: (noteId: string) => void;
  onOpenNote: (noteId: string) => void;
  kindFilter: NoteKind | "all";
  onKindFilterChange: (kind: NoteKind | "all") => void;
}) {
  const kindCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const node of graph?.nodes ?? []) {
      const key = node.kind ?? "note";
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return Array.from(counts.entries());
  }, [graph]);

  const layout = useMemo(() => {
    if (!graph || graph.nodes.length === 0) {
      return [];
    }
    const width = 880;
    const height = 420;
    const centerX = width / 2;
    const centerY = height / 2;
    const focusId = selectedNoteId ?? graph.nodes[0]?.id;
    const others = graph.nodes.filter((node) => node.id !== focusId);
    return graph.nodes.map((node, index) => {
      if (node.id === focusId) {
        return { ...node, x: centerX, y: centerY };
      }
      const angle = (index / Math.max(others.length, 1)) * Math.PI * 2;
      return {
        ...node,
        x: centerX + Math.cos(angle) * 150,
        y: centerY + Math.sin(angle) * 120,
      };
    });
  }, [graph, selectedNoteId]);

  const nodeById = useMemo(
    () => Object.fromEntries(layout.map((node) => [node.id, node])),
    [layout],
  );

  return (
    <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
      <Card padding="lg" className="gap-3">
        <div>
          <h3 className="text-sm font-semibold text-[var(--color-fg-primary)]">Focus Note</h3>
          <p className="mt-1 text-xs text-[var(--color-fg-tertiary)]">
            Choose a note to expand its 1-2 hop neighborhood.
          </p>
        </div>
        <div className="flex max-h-[420px] flex-col gap-2 overflow-y-auto">
          {notes.map((note) => (
            <button
              key={note.id}
              type="button"
              onClick={() => onSelectNote(note.id)}
              className={cn(
                "rounded-[var(--radius-md)] border px-3 py-2 text-left transition-colors",
                selectedNoteId === note.id
                  ? "border-[var(--color-info-500)] bg-[var(--color-info-50)]"
                  : "border-[var(--color-border-default)] bg-[var(--color-bg-surface)] hover:bg-[var(--color-bg-elevated)]",
              )}
            >
              <div className="truncate text-sm font-medium text-[var(--color-fg-primary)]">
                {note.title}
              </div>
              <div className="mt-1 text-xs text-[var(--color-fg-tertiary)]">
                {note.kind ?? "note"}
              </div>
            </button>
          ))}
        </div>
      </Card>

      <Card padding="lg">
        {!graph || graph.nodes.length === 0 ? (
          <EmptyState
            icon={Network}
            title="No graph neighborhood yet"
            description="Select a note with links to explore its graph."
          />
        ) : (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-[var(--color-fg-primary)]">
                  Graph Neighborhood
                </h3>
                <p className="text-xs text-[var(--color-fg-tertiary)]">
                  {graph.nodes.length} notes, {graph.edges.length} links
                </p>
              </div>
              <select
                value={kindFilter}
                onChange={(event) => onKindFilterChange(event.target.value as NoteKind | "all")}
                className="h-8 rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] px-2 text-xs text-[var(--color-fg-primary)]"
              >
                <option value="all">All kinds</option>
                <option value="note">Notes</option>
                <option value="daily">Daily</option>
                <option value="moc">MOCs</option>
              </select>
            </div>
            {kindCounts.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {kindCounts.map(([kind, count]) => (
                  <Badge key={kind} size="sm" variant="default">
                    {kind}: {count}
                  </Badge>
                ))}
              </div>
            )}
            <svg
              viewBox="0 0 880 420"
              className="w-full rounded-[var(--radius-lg)] bg-[radial-gradient(circle_at_center,_rgba(32,94,166,0.10),_transparent_55%),linear-gradient(180deg,rgba(255,255,255,0.85),rgba(240,245,250,0.9))]"
            >
              {graph.edges.map((edge) => {
                const source = nodeById[edge.source];
                const target = nodeById[edge.target];
                if (!source || !target) return null;
                return (
                  <line
                    key={edge.id}
                    x1={source.x}
                    y1={source.y}
                    x2={target.x}
                    y2={target.y}
                    stroke="rgba(44, 93, 142, 0.25)"
                    strokeWidth={edge.link_type === "wiki" ? 2.5 : 1.5}
                  />
                );
              })}
              {layout.map((node) => (
                <g key={node.id} onClick={() => onOpenNote(node.id)} className="cursor-pointer">
                  <circle
                    cx={node.x}
                    cy={node.y}
                    r={selectedNoteId === node.id ? 28 : 22}
                    fill={
                      selectedNoteId === node.id ? "rgba(32,94,166,0.9)" : "rgba(244,248,252,0.95)"
                    }
                    stroke="rgba(32,94,166,0.7)"
                    strokeWidth={2}
                  />
                  <text
                    x={node.x}
                    y={node.y + 4}
                    textAnchor="middle"
                    className="fill-[var(--color-fg-primary)] text-[11px] font-medium"
                  >
                    {node.title.slice(0, 10)}
                  </text>
                </g>
              ))}
            </svg>
          </div>
        )}
      </Card>
    </div>
  );
}

function CanvasPanel({
  canvases,
  onCreate,
  onImport,
  onExport,
}: {
  canvases: NoteCanvas[];
  onCreate: () => void;
  onImport: () => void;
  onExport: (canvas: NoteCanvas) => void;
}) {
  if (canvases.length === 0) {
    return (
      <EmptyState
        icon={PanelsTopLeft}
        title="No canvases yet"
        description="Create a canvas to arrange notes into explicit narrative boards."
        action={{ label: "Create Canvas", onClick: onCreate }}
      />
    );
  }
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-end gap-2">
        <Button size="sm" variant="outline" className="gap-1.5" onClick={onImport}>
          <Upload className="h-4 w-4" />
          Import JSON
        </Button>
        <Button size="sm" className="gap-1.5" onClick={onCreate}>
          <Plus className="h-4 w-4" />
          New Canvas
        </Button>
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {canvases.map((canvas) => (
          <Card key={canvas.id} padding="lg" className="gap-3">
            <div className="flex items-start justify-between gap-3">
              <div className="text-sm font-semibold text-[var(--color-fg-primary)]">
                {canvas.title}
              </div>
              <Button
                size="sm"
                variant="ghost"
                className="gap-1.5"
                onClick={() => onExport(canvas)}
              >
                <Download className="h-3.5 w-3.5" />
                Export
              </Button>
            </div>
            {canvas.description && (
              <p className="text-sm text-[var(--color-fg-secondary)]">{canvas.description}</p>
            )}
            <div className="flex items-center gap-2 text-xs text-[var(--color-fg-tertiary)]">
              <Badge size="sm" variant="info">
                {canvas.nodes.length} nodes
              </Badge>
              <Badge size="sm" variant="default">
                {canvas.edges.length} edges
              </Badge>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}

function ContentPanel({
  items,
  busyAssetId,
  onRegenerateSourcePack,
  onExportSourcePack,
  onUpdateStatus,
}: {
  items: ContentAsset[];
  busyAssetId: string | null;
  onRegenerateSourcePack: (assetId: string) => void;
  onExportSourcePack: (asset: ContentAsset) => void;
  onUpdateStatus: (assetId: string, status: string) => void;
}) {
  if (items.length === 0) {
    return (
      <EmptyState
        icon={Radio}
        title="No content assets queued"
        description="Create a NotebookLM podcast asset from a note to start the content factory."
      />
    );
  }
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {items.map((item) => (
        <Card key={item.id} padding="lg" className="gap-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold text-[var(--color-fg-primary)]">{item.title}</h3>
              <p className="text-xs text-[var(--color-fg-tertiary)]">{item.asset_type}</p>
            </div>
            <Badge
              size="sm"
              variant={
                item.status === "done"
                  ? "success"
                  : item.status === "needs_review"
                    ? "warning"
                    : "info"
              }
            >
              {item.status}
            </Badge>
          </div>
          {item.run_notes && (
            <p className="text-sm text-[var(--color-fg-secondary)]">{item.run_notes}</p>
          )}
          <p className="text-xs text-[var(--color-fg-tertiary)]">
            Source docs:{" "}
            {Array.isArray(item.source_pack?.documents) ? item.source_pack.documents.length : 0}
          </p>
          <p className="text-xs text-[var(--color-fg-tertiary)]">
            Linked note: {item.note_id ?? "none"}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="outline"
              loading={busyAssetId === item.id}
              onClick={() => onRegenerateSourcePack(item.id)}
            >
              Refresh pack
            </Button>
            <Button size="sm" variant="outline" onClick={() => onExportSourcePack(item)}>
              Export JSON
            </Button>
            {["ready", "in_progress", "needs_review", "done"].map((status) => (
              <Button
                key={status}
                size="sm"
                variant={item.status === status ? "default" : "ghost"}
                onClick={() => onUpdateStatus(item.id, status)}
              >
                {status}
              </Button>
            ))}
          </div>
        </Card>
      ))}
    </div>
  );
}

function NotesPage() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<NotesTab>("all");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortOption>("newest");
  const [filterNoteType, setFilterNoteType] = useState<NoteType | "all">("all");
  const [filterParaCategory, setFilterParaCategory] = useState<ParaCategory | "all">("all");
  const [selectedNoteId, setSelectedNoteId] = useState<string | null>(null);
  const [graphNoteId, setGraphNoteId] = useState<string | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [graphKindFilter, setGraphKindFilter] = useState<NoteKind | "all">("all");
  const [canvasImportOpen, setCanvasImportOpen] = useState(false);
  const [canvasImportText, setCanvasImportText] = useState("");
  const [busyContentAssetId, setBusyContentAssetId] = useState<string | null>(null);

  const debouncedSearch = useDebounce(search, 300);

  const allNotesQuery = useQuery({
    queryKey: ["notes", debouncedSearch, filterNoteType, filterParaCategory],
    queryFn: () =>
      listNotes({
        limit: 100,
        search: debouncedSearch.trim() || undefined,
        note_type: filterNoteType === "all" ? undefined : filterNoteType,
        para_category: filterParaCategory === "all" ? undefined : filterParaCategory,
      }),
  });

  const dailyNotesQuery = useQuery({
    queryKey: ["notes", "daily"],
    queryFn: () => listNotes({ limit: 30, kind: "daily" as NoteKind }),
  });

  const mocNotesQuery = useQuery({
    queryKey: ["notes", "moc"],
    queryFn: () => listNotes({ limit: 50, kind: "moc" as NoteKind }),
  });

  const canvasesQuery = useQuery({
    queryKey: ["note-canvases"],
    queryFn: () => listNoteCanvases(50, 0),
  });

  const contentAssetsQuery = useQuery({
    queryKey: ["content-assets"],
    queryFn: () => getContentAssets({ limit: 50, offset: 0 }),
  });

  const activeGraphNoteId = graphNoteId ?? allNotesQuery.data?.items?.[0]?.id ?? null;

  const graphQuery = useQuery({
    queryKey: ["notes-graph", activeGraphNoteId, graphKindFilter],
    queryFn: () =>
      getNoteGraph({
        note_id: activeGraphNoteId ?? undefined,
        depth: 2,
        limit: 40,
        kind: graphKindFilter === "all" ? undefined : graphKindFilter,
      }),
    enabled: activeTab === "graph",
  });

  const createDailyMutation = useMutation({
    mutationFn: () =>
      upsertDailyNote(todayIsoDate(), {
        title: `Daily Note ${todayIsoDate()}`,
        content: `# Daily Note\n\n- What moved today?\n- What is blocked?\n- Which note should link here?\n`,
      }),
    onSuccess: (note) => {
      queryClient.invalidateQueries({ queryKey: ["notes", "daily"] });
      setSelectedNoteId(note.id);
    },
  });

  const createCanvasMutation = useMutation({
    mutationFn: () =>
      createNoteCanvas({
        title: "New Canvas",
        description: "A note-centric planning board.",
        primary_note_id: activeGraphNoteId ?? undefined,
        nodes: activeGraphNoteId ? [{ id: activeGraphNoteId, x: 320, y: 180 }] : [],
        edges: [],
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["note-canvases"] });
    },
  });

  const importCanvasMutation = useMutation({
    mutationFn: async () => {
      const parsed = JSON.parse(canvasImportText) as Record<string, unknown>;
      return createNoteCanvas({
        title: typeof parsed.title === "string" ? parsed.title : "Imported Canvas",
        description: typeof parsed.description === "string" ? parsed.description : undefined,
        primary_note_id:
          typeof parsed.primary_note_id === "string" ? parsed.primary_note_id : undefined,
        nodes: Array.isArray(parsed.nodes) ? (parsed.nodes as Array<Record<string, unknown>>) : [],
        edges: Array.isArray(parsed.edges) ? (parsed.edges as Array<Record<string, unknown>>) : [],
        viewport:
          parsed.viewport && typeof parsed.viewport === "object"
            ? (parsed.viewport as Record<string, unknown>)
            : undefined,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["note-canvases"] });
      setCanvasImportOpen(false);
      setCanvasImportText("");
    },
  });

  const regenerateSourcePackMutation = useMutation({
    mutationFn: async (assetId: string) => {
      setBusyContentAssetId(assetId);
      return generateContentAssetSourcePack(assetId);
    },
    onSettled: () => {
      setBusyContentAssetId(null);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["content-assets"] });
    },
  });

  const updateContentAssetMutation = useMutation({
    mutationFn: ({ assetId, status }: { assetId: string; status: string }) =>
      updateContentAsset(assetId, { status }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["content-assets"] });
    },
  });

  const rawNotes = useMemo(() => allNotesQuery.data?.items ?? [], [allNotesQuery.data?.items]);
  const filteredNotes = useMemo(() => sortNotes(rawNotes, sort), [rawNotes, sort]);
  const dailyNotes = dailyNotesQuery.data?.items ?? [];
  const mocNotes = mocNotesQuery.data?.items ?? [];
  const canvases = canvasesQuery.data?.items ?? [];
  const contentAssets = contentAssetsQuery.data?.items ?? [];
  const hasActiveFilters = filterNoteType !== "all" || filterParaCategory !== "all";

  function exportCanvas(canvas: NoteCanvas): void {
    const blob = new Blob([JSON.stringify(canvas, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${canvas.title.toLowerCase().replace(/[^a-z0-9]+/g, "-") || "canvas"}.canvas.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  function exportSourcePack(asset: ContentAsset): void {
    const blob = new Blob([JSON.stringify(asset.source_pack ?? {}, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${asset.title.toLowerCase().replace(/[^a-z0-9]+/g, "-") || "content-asset"}.source-pack.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  if (selectedNoteId) {
    return (
      <NoteDetail
        noteId={selectedNoteId}
        onBack={() => setSelectedNoteId(null)}
        onNavigateNote={setSelectedNoteId}
      />
    );
  }

  const selectClass =
    "h-8 rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] px-2 text-xs text-[var(--color-fg-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-border-focus)]";

  return (
    <PageTransition>
      <div className="flex flex-col gap-6 p-6">
        <PageHeader
          title="Notes Workspace"
          subtitle="Graph-native notes, daily logs, canvases, and content repurposing"
          icon={NotebookTabs}
          agentColor="memory"
        >
          <Button size="sm" className="w-fit gap-1.5" onClick={() => setEditorOpen(true)}>
            <Plus className="h-4 w-4" />
            New Note
          </Button>
        </PageHeader>

        <Tabs.Root value={activeTab} onValueChange={(value) => setActiveTab(value as NotesTab)}>
          <Tabs.List className="flex flex-wrap items-center gap-1 border-b border-[var(--color-border-default)]">
            {tabs.map((tab) => (
              <Tabs.Trigger
                key={tab.value}
                value={tab.value}
                className={cn(
                  "relative px-4 py-2.5 text-sm font-medium transition-colors",
                  "text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-secondary)]",
                  "data-[state=active]:text-[var(--color-fg-primary)]",
                  "after:absolute after:bottom-0 after:left-0 after:right-0 after:h-0.5 after:transition-colors",
                  "data-[state=active]:after:bg-[var(--color-info-500)] after:bg-transparent",
                )}
              >
                {tab.label}
              </Tabs.Trigger>
            ))}
          </Tabs.List>

          <div className="mt-6 space-y-6">
            <Tabs.Content value="all" className="space-y-4">
              <div className="flex flex-wrap items-center gap-2">
                <div className="relative max-w-sm flex-1">
                  <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-fg-tertiary)]" />
                  <Input
                    placeholder="Search notes..."
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    className="pl-9"
                  />
                </div>
                <select
                  value={filterNoteType}
                  onChange={(e) => setFilterNoteType(e.target.value as NoteType | "all")}
                  className={selectClass}
                >
                  <option value="all">All types</option>
                  {noteTypeOptions.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
                <select
                  value={filterParaCategory}
                  onChange={(e) => setFilterParaCategory(e.target.value as ParaCategory | "all")}
                  className={selectClass}
                >
                  <option value="all">All PARA</option>
                  {paraCategoryOptions.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
                <SortMenu
                  value={sort}
                  options={sortOptions}
                  onChange={setSort}
                  buttonLabel={sortOptions.find((opt) => opt.value === sort)?.label ?? "Sort"}
                  buttonAriaLabel="Sort notes"
                  widthClassName="w-44"
                />
                {hasActiveFilters && (
                  <button
                    onClick={() => {
                      setFilterNoteType("all");
                      setFilterParaCategory("all");
                    }}
                    className="flex items-center gap-1 text-xs text-[var(--color-fg-secondary)] hover:text-[var(--color-fg-primary)] transition-colors cursor-pointer"
                  >
                    <X className="h-3 w-3" />
                    Clear filters
                  </button>
                )}
              </div>

              {allNotesQuery.isError && (
                <PageError
                  message={allNotesQuery.error?.message ?? "Failed to load notes"}
                  onRetry={() => allNotesQuery.refetch()}
                  context="your notes"
                  icon={StickyNote}
                />
              )}

              {allNotesQuery.isLoading ? (
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {Array.from({ length: 9 }).map((_, index) => (
                    <Skeleton key={index} className="h-48 w-full" />
                  ))}
                </div>
              ) : filteredNotes.length === 0 ? (
                <EmptyState
                  icon={search ? Search : StickyNote}
                  title={search ? "No notes match your search" : "No notes yet"}
                  description={
                    search
                      ? "Try a different search term."
                      : "Create your first note to start building your graph."
                  }
                />
              ) : (
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {filteredNotes.map((note) => (
                    <NoteCard
                      key={note.id}
                      note={note}
                      selected={false}
                      onSelect={(selected) => setSelectedNoteId(selected.id)}
                    />
                  ))}
                </div>
              )}
            </Tabs.Content>

            <Tabs.Content value="graph">
              <GraphPanel
                notes={filteredNotes}
                graph={graphQuery.data}
                selectedNoteId={activeGraphNoteId}
                onSelectNote={setGraphNoteId}
                onOpenNote={setSelectedNoteId}
                kindFilter={graphKindFilter}
                onKindFilterChange={setGraphKindFilter}
              />
            </Tabs.Content>

            <Tabs.Content value="daily" className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-semibold text-[var(--color-fg-primary)]">
                    Daily Notes
                  </h3>
                  <p className="text-xs text-[var(--color-fg-tertiary)]">
                    Ordinary notes with a calendar anchor.
                  </p>
                </div>
                <Button
                  size="sm"
                  className="gap-1.5"
                  loading={createDailyMutation.isPending}
                  onClick={() => createDailyMutation.mutate()}
                >
                  <Plus className="h-4 w-4" />
                  Today
                </Button>
              </div>
              {dailyNotes.length === 0 ? (
                <EmptyState
                  icon={BookOpen}
                  title="No daily notes yet"
                  description="Create today's note to start a running log."
                />
              ) : (
                <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                  {dailyNotes.map((note) => (
                    <NoteCard
                      key={note.id}
                      note={note}
                      selected={false}
                      onSelect={(selected) => setSelectedNoteId(selected.id)}
                    />
                  ))}
                </div>
              )}
            </Tabs.Content>

            <Tabs.Content value="moc">
              {mocNotes.length === 0 ? (
                <EmptyState
                  icon={BookOpen}
                  title="No MOC notes yet"
                  description="Create notes with kind=moc to build maps of content."
                />
              ) : (
                <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                  {mocNotes.map((note) => (
                    <NoteCard
                      key={note.id}
                      note={note}
                      selected={false}
                      onSelect={(selected) => setSelectedNoteId(selected.id)}
                    />
                  ))}
                </div>
              )}
            </Tabs.Content>

            <Tabs.Content value="canvases">
              <CanvasPanel
                canvases={canvases}
                onCreate={() => createCanvasMutation.mutate()}
                onImport={() => setCanvasImportOpen(true)}
                onExport={exportCanvas}
              />
            </Tabs.Content>

            <Tabs.Content value="content">
              <ContentPanel
                items={contentAssets}
                busyAssetId={busyContentAssetId}
                onRegenerateSourcePack={(assetId) => regenerateSourcePackMutation.mutate(assetId)}
                onExportSourcePack={exportSourcePack}
                onUpdateStatus={(assetId, status) =>
                  updateContentAssetMutation.mutate({ assetId, status })
                }
              />
            </Tabs.Content>
          </div>
        </Tabs.Root>

        {editorOpen && (
          <NoteEditor
            onClose={() => setEditorOpen(false)}
            onSaved={() => {
              setEditorOpen(false);
              queryClient.invalidateQueries({ queryKey: ["notes"] });
            }}
          />
        )}

        {canvasImportOpen && (
          <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 px-4">
            <Card padding="lg" className="w-full max-w-2xl gap-4">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-base font-semibold text-[var(--color-fg-primary)]">
                    Import Canvas JSON
                  </h3>
                  <p className="text-sm text-[var(--color-fg-secondary)]">
                    Paste exported canvas JSON to recreate a board.
                  </p>
                </div>
                <Button variant="ghost" size="icon" onClick={() => setCanvasImportOpen(false)}>
                  <X className="h-4 w-4" />
                </Button>
              </div>
              <textarea
                value={canvasImportText}
                onChange={(event) => setCanvasImportText(event.target.value)}
                rows={14}
                className="w-full rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] px-3 py-2 font-mono text-xs text-[var(--color-fg-primary)]"
              />
              {importCanvasMutation.isError && (
                <p className="text-xs text-[var(--color-error-500)]">
                  {importCanvasMutation.error instanceof Error
                    ? importCanvasMutation.error.message
                    : "Canvas import failed"}
                </p>
              )}
              <div className="flex justify-end gap-2">
                <Button variant="ghost" onClick={() => setCanvasImportOpen(false)}>
                  Cancel
                </Button>
                <Button
                  loading={importCanvasMutation.isPending}
                  disabled={!canvasImportText.trim()}
                  onClick={() => importCanvasMutation.mutate()}
                >
                  Import Canvas
                </Button>
              </div>
            </Card>
          </div>
        )}
      </div>
    </PageTransition>
  );
}

export { NotesPage };

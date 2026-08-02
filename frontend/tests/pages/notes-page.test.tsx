import { fireEvent } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent, waitFor } from "../test-utils";
import { NotesPage } from "@/pages/notes";
import { createNote, createPaginatedResponse } from "../factories";
import type { ContentAsset, Note, NoteCanvas, NoteGraph } from "@/types";

const mocks = vi.hoisted(() => ({
  createNoteCanvas: vi.fn(),
  generateContentAssetSourcePack: vi.fn(),
  getContentAssets: vi.fn(),
  getNoteGraph: vi.fn(),
  listNoteCanvases: vi.fn(),
  listNotes: vi.fn(),
  updateContentAsset: vi.fn(),
  upsertDailyNote: vi.fn(),
}));

vi.mock("@/api/notes", () => ({
  createNoteCanvas: mocks.createNoteCanvas,
  getNoteGraph: mocks.getNoteGraph,
  listNoteCanvases: mocks.listNoteCanvases,
  listNotes: mocks.listNotes,
  upsertDailyNote: mocks.upsertDailyNote,
}));

vi.mock("@/api/content-assets", () => ({
  generateContentAssetSourcePack: mocks.generateContentAssetSourcePack,
  getContentAssets: mocks.getContentAssets,
  updateContentAsset: mocks.updateContentAsset,
}));

vi.mock("@radix-ui/react-tabs", async () => {
  const React = await import("react");
  const TabsContext = React.createContext<{
    value: string;
    onValueChange: (value: string) => void;
  } | null>(null);

  return {
    Root: ({
      children,
      value,
      onValueChange,
    }: {
      children: React.ReactNode;
      value: string;
      onValueChange: (value: string) => void;
    }) => <TabsContext.Provider value={{ value, onValueChange }}>{children}</TabsContext.Provider>,
    List: ({ children }: { children: React.ReactNode }) => <div role="tablist">{children}</div>,
    Trigger: ({ children, value }: { children: React.ReactNode; value: string }) => {
      const context = React.useContext(TabsContext);
      return (
        <button
          type="button"
          role="tab"
          aria-selected={context?.value === value}
          onClick={() => context?.onValueChange(value)}
        >
          {children}
        </button>
      );
    },
    Content: ({ children, value }: { children: React.ReactNode; value: string }) => {
      const context = React.useContext(TabsContext);
      return context?.value === value ? <div>{children}</div> : null;
    },
  };
});

vi.mock("@/components/ui/page-transition", () => ({
  PageTransition: ({ children }: { children: React.ReactNode }) => children,
}));

vi.mock("@/hooks/use-debounce", () => ({
  useDebounce: (value: string) => value,
}));

vi.mock("@/components/ui/page-header", () => ({
  PageHeader: ({
    children,
    subtitle,
    title,
  }: {
    children?: React.ReactNode;
    subtitle: string;
    title: string;
  }) => (
    <header>
      <h1>{title}</h1>
      <p>{subtitle}</p>
      {children}
    </header>
  ),
}));

vi.mock("@/components/ui/page-error", () => ({
  PageError: ({
    context,
    message,
    onRetry,
  }: {
    context: string;
    message: string;
    onRetry: () => void;
  }) => (
    <div role="alert">
      Page Error: {message} ({context})
      <button type="button" onClick={onRetry}>
        Retry notes
      </button>
    </div>
  ),
}));

vi.mock("@/components/ui/empty-state", () => ({
  EmptyState: ({
    action,
    description,
    title,
  }: {
    action?: { label: string; onClick: () => void };
    description: string;
    title: string;
  }) => (
    <section aria-label={title}>
      <h2>{title}</h2>
      <p>{description}</p>
      {action && (
        <button type="button" onClick={action.onClick}>
          {action.label}
        </button>
      )}
    </section>
  ),
}));

vi.mock("@/components/ui/skeleton", () => ({
  Skeleton: () => <div data-testid="notes-skeleton" />,
}));

vi.mock("@/components/ui/sort-menu", () => ({
  SortMenu: ({
    buttonAriaLabel,
    onChange,
    options,
    value,
  }: {
    buttonAriaLabel: string;
    onChange: (value: string) => void;
    options: Array<{ label: string; value: string }>;
    value: string;
  }) => (
    <select
      aria-label={buttonAriaLabel}
      value={value}
      onChange={(event) => onChange(event.target.value)}
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  ),
}));

vi.mock("@/components/notes/note-card", () => ({
  NoteCard: ({ note, onSelect }: { note: Note; onSelect: (note: Note) => void }) => (
    <button type="button" onClick={() => onSelect(note)}>
      Open {note.title}
    </button>
  ),
}));

vi.mock("@/components/notes/note-detail", () => ({
  NoteDetail: ({
    noteId,
    onBack,
    onNavigateNote,
  }: {
    noteId: string;
    onBack: () => void;
    onNavigateNote: (noteId: string) => void;
  }) => (
    <section aria-label="Note detail">
      <div>Detail {noteId}</div>
      <button type="button" onClick={() => onNavigateNote("linked-note")}>
        Open linked note
      </button>
      <button type="button" onClick={onBack}>
        Back to notes
      </button>
    </section>
  ),
}));

vi.mock("@/components/notes/note-editor", () => ({
  NoteEditor: ({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) => (
    <section aria-label="Note editor">
      <button type="button" onClick={onSaved}>
        Save note
      </button>
      <button type="button" onClick={onClose}>
        Close editor
      </button>
    </section>
  ),
}));

function createCanvas(overrides: Partial<NoteCanvas> = {}): NoteCanvas {
  return {
    id: "canvas-1",
    title: "Research Board",
    description: "A connected research narrative",
    primary_note_id: "note-1",
    nodes: [{ id: "note-1", x: 10, y: 20 }],
    edges: [{ source: "note-1", target: "note-2" }],
    viewport: { x: 0, y: 0, zoom: 1 },
    created_at: "2026-07-01T09:00:00Z",
    updated_at: "2026-07-01T09:00:00Z",
    ...overrides,
  };
}

function createContentAsset(overrides: Partial<ContentAsset> = {}): ContentAsset {
  return {
    id: "asset-1",
    note_id: "note-1",
    project_id: null,
    task_id: null,
    title: "Research Podcast",
    asset_type: "notebooklm_podcast",
    status: "ready",
    source_pack: { documents: [{ title: "Source one" }] },
    template_prompt: null,
    run_notes: "Ready for review",
    metadata: {},
    created_at: "2026-07-01T09:00:00Z",
    updated_at: "2026-07-01T09:00:00Z",
    ...overrides,
  };
}

function createGraph(notes: Note[]): NoteGraph {
  return {
    nodes: notes.map((note) => ({
      id: note.id,
      title: note.title,
      slug: note.slug,
      kind: note.kind,
      note_type: note.note_type,
      para_category: note.para_category,
      tags: note.tags,
      created_at: note.created_at,
      updated_at: note.updated_at,
    })),
    edges: [
      {
        id: "edge-wiki",
        source: notes[0].id,
        target: notes[1].id,
        link_type: "wiki",
        origin: "manual",
        similarity_score: null,
        link_reason: null,
      },
      {
        id: "edge-semantic",
        source: notes[1].id,
        target: notes[2].id,
        link_type: "semantic",
        origin: "automatic",
        similarity_score: 0.91,
        link_reason: "Related themes",
      },
      {
        id: "edge-missing-node",
        source: notes[0].id,
        target: "missing",
        link_type: "wiki",
        origin: "manual",
        similarity_score: null,
        link_reason: null,
      },
    ],
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

const alpha = createNote({
  id: "note-1",
  title: "Alpha note",
  note_type: "permanent",
  para_category: "resource",
  created_at: "2026-04-01T09:00:00Z",
  updated_at: "2026-04-01T09:00:00Z",
});

const beta = createNote({
  id: "note-2",
  title: "Beta note",
  note_type: "literature",
  para_category: "project",
  created_at: "2026-04-03T09:00:00Z",
  updated_at: "2026-04-03T09:00:00Z",
});

const daily = createNote({
  id: "daily-1",
  title: "Daily Log",
  kind: "daily",
  daily_date: "2026-08-02",
});

const moc = createNote({
  id: "moc-1",
  title: "Product MOC",
  kind: "moc",
});

function arrangeNotes({
  all = [alpha, beta],
  dailyNotes = [],
  mocNotes = [],
}: {
  all?: Note[];
  dailyNotes?: Note[];
  mocNotes?: Note[];
} = {}) {
  mocks.listNotes.mockImplementation(
    async (params?: {
      kind?: string;
      note_type?: string;
      para_category?: string;
      search?: string;
    }) => {
      if (params?.kind === "daily") return createPaginatedResponse(dailyNotes);
      if (params?.kind === "moc") return createPaginatedResponse(mocNotes);

      let items = all;
      if (params?.search) {
        const query = params.search.toLowerCase();
        items = items.filter((note) => note.title.toLowerCase().includes(query));
      }
      if (params?.note_type) {
        items = items.filter((note) => note.note_type === params.note_type);
      }
      if (params?.para_category) {
        items = items.filter((note) => note.para_category === params.para_category);
      }
      return createPaginatedResponse(items);
    },
  );
}

const originalCreateObjectUrl = URL.createObjectURL;
const originalRevokeObjectUrl = URL.revokeObjectURL;

describe("NotesPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    arrangeNotes();
    mocks.getNoteGraph.mockResolvedValue({ nodes: [], edges: [] });
    mocks.listNoteCanvases.mockResolvedValue(createPaginatedResponse([]));
    mocks.getContentAssets.mockResolvedValue(createPaginatedResponse([]));
    mocks.upsertDailyNote.mockResolvedValue(daily);
    mocks.createNoteCanvas.mockResolvedValue(createCanvas());
    mocks.generateContentAssetSourcePack.mockResolvedValue(createContentAsset());
    mocks.updateContentAsset.mockResolvedValue(createContentAsset());

    URL.createObjectURL = vi.fn(() => "blob:notes-export");
    URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
  });

  afterEach(() => {
    URL.createObjectURL = originalCreateObjectUrl;
    URL.revokeObjectURL = originalRevokeObjectUrl;
    vi.restoreAllMocks();
  });

  it("shows the loading grid while the primary notes request is pending", () => {
    const allNotes = deferred<ReturnType<typeof createPaginatedResponse<Note>>>();
    mocks.listNotes.mockImplementation((params?: { kind?: string }) => {
      if (params?.kind) return Promise.resolve(createPaginatedResponse([]));
      return allNotes.promise;
    });

    renderWithProviders(<NotesPage />);

    expect(screen.getByRole("heading", { name: "Notes Workspace" })).toBeInTheDocument();
    expect(screen.getAllByTestId("notes-skeleton")).toHaveLength(9);
  });

  it("renders a load error, retries the request, and then shows the empty state", async () => {
    const user = userEvent.setup();
    let attempts = 0;
    mocks.listNotes.mockImplementation(async (params?: { kind?: string }) => {
      if (params?.kind) return createPaginatedResponse([]);
      attempts += 1;
      if (attempts === 1) throw new Error("notes failed");
      return createPaginatedResponse([]);
    });

    renderWithProviders(<NotesPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Page Error: notes failed (your notes)",
    );
    await user.click(screen.getByRole("button", { name: "Retry notes" }));
    expect(await screen.findByRole("heading", { name: "No notes yet" })).toBeInTheDocument();
    expect(attempts).toBe(2);
  });

  it("searches, filters, clears filters, sorts every way, and follows linked-note navigation", async () => {
    const user = userEvent.setup();
    renderWithProviders(<NotesPage />);

    expect(await screen.findByRole("button", { name: "Open Beta note" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Open (Alpha|Beta) note/ })[0]).toHaveTextContent(
      "Open Beta note",
    );
    expect(mocks.listNotes).toHaveBeenCalledWith({
      limit: 100,
      note_type: undefined,
      para_category: undefined,
      search: undefined,
    });

    await user.selectOptions(screen.getByRole("combobox", { name: "Sort notes" }), "oldest");
    expect(screen.getAllByRole("button", { name: /Open (Alpha|Beta) note/ })[0]).toHaveTextContent(
      "Open Alpha note",
    );
    await user.selectOptions(screen.getByRole("combobox", { name: "Sort notes" }), "title_asc");
    expect(screen.getAllByRole("button", { name: /Open (Alpha|Beta) note/ })[0]).toHaveTextContent(
      "Open Alpha note",
    );
    await user.selectOptions(screen.getByRole("combobox", { name: "Sort notes" }), "title_desc");
    expect(screen.getAllByRole("button", { name: /Open (Alpha|Beta) note/ })[0]).toHaveTextContent(
      "Open Beta note",
    );

    await user.type(screen.getByPlaceholderText("Search notes..."), "Alpha");
    expect(await screen.findByRole("button", { name: "Open Alpha note" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open Beta note" })).not.toBeInTheDocument();
    await user.clear(screen.getByPlaceholderText("Search notes..."));
    expect(await screen.findByRole("button", { name: "Open Beta note" })).toBeInTheDocument();
    await user.type(screen.getByPlaceholderText("Search notes..."), "Missing");
    expect(
      await screen.findByRole("heading", { name: "No notes match your search" }),
    ).toBeInTheDocument();
    await user.clear(screen.getByPlaceholderText("Search notes..."));
    expect(await screen.findByRole("button", { name: "Open Beta note" })).toBeInTheDocument();

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Note type filter" }),
      "permanent",
    );
    expect(await screen.findByRole("button", { name: "Open Alpha note" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open Beta note" })).not.toBeInTheDocument();
    await user.selectOptions(
      screen.getByRole("combobox", { name: "PARA category filter" }),
      "resource",
    );
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(await screen.findByRole("button", { name: "Open Beta note" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Open Alpha note" }));
    expect(screen.getByText("Detail note-1")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open linked note" }));
    expect(screen.getByText("Detail linked-note")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Back to notes" }));
    expect(await screen.findByRole("button", { name: "Open Alpha note" })).toBeInTheDocument();
  });

  it("opens, closes, and saves the note editor, invalidating the notes collection", async () => {
    const user = userEvent.setup();
    renderWithProviders(<NotesPage />);

    await screen.findByRole("button", { name: "Open Alpha note" });
    await user.click(screen.getByRole("button", { name: "New Note" }));
    expect(screen.getByRole("region", { name: "Note editor" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Close editor" }));
    expect(screen.queryByRole("region", { name: "Note editor" })).not.toBeInTheDocument();

    const callsBeforeSave = mocks.listNotes.mock.calls.length;
    await user.click(screen.getByRole("button", { name: "New Note" }));
    await user.click(screen.getByRole("button", { name: "Save note" }));
    expect(screen.queryByRole("region", { name: "Note editor" })).not.toBeInTheDocument();
    await waitFor(() => expect(mocks.listNotes.mock.calls.length).toBeGreaterThan(callsBeforeSave));
  });

  it("renders daily and MOC notes, creates today's note, and opens note cards", async () => {
    const user = userEvent.setup();
    arrangeNotes({ dailyNotes: [daily], mocNotes: [moc] });
    renderWithProviders(<NotesPage />);

    await screen.findByRole("button", { name: "Open Beta note" });
    await user.click(screen.getByRole("tab", { name: "Daily" }));
    expect(screen.getByRole("heading", { name: "Daily Notes" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open Daily Log" }));
    expect(screen.getByText("Detail daily-1")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Back to notes" }));

    await user.click(screen.getByRole("button", { name: "Today" }));
    await waitFor(() => expect(mocks.upsertDailyNote).toHaveBeenCalledTimes(1));
    expect(mocks.upsertDailyNote).toHaveBeenCalledWith(
      expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
      expect.objectContaining({
        title: expect.stringContaining("Daily Note"),
        content: expect.stringContaining("What moved today?"),
      }),
    );
    expect(await screen.findByText("Detail daily-1")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Back to notes" }));

    await user.click(screen.getByRole("tab", { name: "MOCs" }));
    await user.click(screen.getByRole("button", { name: "Open Product MOC" }));
    expect(screen.getByText("Detail moc-1")).toBeInTheDocument();
  });

  it("shows the graph's empty state, then filters, refocuses, and opens linked graph nodes", async () => {
    const user = userEvent.setup();
    const graphNotes = [
      alpha,
      { ...beta, kind: "daily" as const },
      createNote({ id: "note-3", title: "Gamma", kind: null }),
    ];
    let graph: NoteGraph = { nodes: [], edges: [] };
    mocks.getNoteGraph.mockImplementation(async () => graph);
    arrangeNotes({ all: graphNotes });

    renderWithProviders(<NotesPage />);
    await screen.findByRole("button", { name: "Open Beta note" });
    await user.click(screen.getByRole("tab", { name: "Graph" }));
    expect(await screen.findByRole("heading", { name: "No graph neighborhood yet" })).toBeVisible();

    graph = createGraph(graphNotes);
    await user.click(screen.getByRole("button", { name: /Beta note/ }));
    expect(await screen.findByText("3 notes, 3 links")).toBeInTheDocument();
    expect(mocks.getNoteGraph).toHaveBeenLastCalledWith({
      note_id: "note-2",
      depth: 2,
      limit: 40,
      kind: undefined,
    });

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Graph note kind filter" }),
      "daily",
    );
    await waitFor(() =>
      expect(mocks.getNoteGraph).toHaveBeenLastCalledWith({
        note_id: "note-2",
        depth: 2,
        limit: 40,
        kind: "daily",
      }),
    );
    expect(screen.getByText("note: 2")).toBeInTheDocument();
    expect(screen.getByText("daily: 1")).toBeInTheDocument();

    const betaLabels = screen.getAllByText("Beta note");
    await user.click(betaLabels[betaLabels.length - 1]);
    expect(screen.getByText("Detail note-2")).toBeInTheDocument();
  });

  it("covers empty tab states and creates a canvas with no active note", async () => {
    const user = userEvent.setup();
    arrangeNotes({ all: [] });
    mocks.getNoteGraph.mockResolvedValue(
      createGraph([alpha, beta, createNote({ id: "note-3", title: "Gamma" })]),
    );
    renderWithProviders(<NotesPage />);

    expect(await screen.findByRole("heading", { name: "No notes yet" })).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Daily" }));
    expect(screen.getByRole("heading", { name: "No daily notes yet" })).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "MOCs" }));
    expect(screen.getByRole("heading", { name: "No MOC notes yet" })).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Graph" }));
    expect(await screen.findByText("3 notes, 3 links")).toBeInTheDocument();
    expect(mocks.getNoteGraph).toHaveBeenCalledWith({
      note_id: undefined,
      depth: 2,
      limit: 40,
      kind: undefined,
    });
    await user.click(screen.getByRole("tab", { name: "Canvases" }));
    await user.click(screen.getByRole("button", { name: "Create Canvas" }));
    await waitFor(() =>
      expect(mocks.createNoteCanvas).toHaveBeenCalledWith({
        title: "New Canvas",
        description: "A note-centric planning board.",
        primary_note_id: undefined,
        nodes: [],
        edges: [],
      }),
    );
    await user.click(screen.getByRole("tab", { name: "Content" }));
    expect(screen.getByRole("heading", { name: "No content assets queued" })).toBeInTheDocument();
  });

  it("creates, exports, imports, and validates canvases", async () => {
    const user = userEvent.setup();
    const canvas = createCanvas();
    const punctuationCanvas = createCanvas({
      id: "canvas-2",
      title: "",
      description: null,
      nodes: [],
      edges: [],
    });
    mocks.listNoteCanvases.mockResolvedValue(createPaginatedResponse([canvas, punctuationCanvas]));

    renderWithProviders(<NotesPage />);
    await screen.findByRole("button", { name: "Open Alpha note" });
    await user.click(screen.getByRole("tab", { name: "Canvases" }));
    expect(screen.getByText("A connected research narrative")).toBeInTheDocument();
    expect(screen.getByText("1 nodes")).toBeInTheDocument();
    expect(screen.getAllByText("0 nodes")).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: "New Canvas" }));
    await waitFor(() =>
      expect(mocks.createNoteCanvas).toHaveBeenCalledWith(
        expect.objectContaining({
          primary_note_id: "note-1",
          nodes: [{ id: "note-1", x: 320, y: 180 }],
        }),
      ),
    );

    const exportButtons = screen.getAllByRole("button", { name: "Export" });
    await user.click(exportButtons[0]);
    await user.click(exportButtons[1]);
    expect(URL.createObjectURL).toHaveBeenCalledTimes(2);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:notes-export");
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledTimes(2);

    await user.click(screen.getByRole("button", { name: "Import JSON" }));
    expect(screen.getByRole("heading", { name: "Import Canvas JSON" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("heading", { name: "Import Canvas JSON" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Import JSON" }));
    const canvasJson = {
      title: "Imported Story",
      description: "Imported description",
      primary_note_id: "note-2",
      nodes: [{ id: "note-2" }],
      edges: [{ source: "note-2", target: "note-1" }],
      viewport: { zoom: 1.5 },
    };
    fireEvent.change(screen.getByRole("textbox", { name: "Canvas JSON to import" }), {
      target: { value: JSON.stringify(canvasJson) },
    });
    await user.click(screen.getByRole("button", { name: "Import Canvas" }));
    await waitFor(() => expect(mocks.createNoteCanvas).toHaveBeenCalledWith(canvasJson));
    expect(screen.queryByRole("heading", { name: "Import Canvas JSON" })).not.toBeInTheDocument();
  });

  it("uses safe canvas import fallbacks and reports malformed JSON", async () => {
    const user = userEvent.setup();
    mocks.listNoteCanvases.mockResolvedValue(createPaginatedResponse([createCanvas()]));
    renderWithProviders(<NotesPage />);

    await screen.findByRole("button", { name: "Open Alpha note" });
    await user.click(screen.getByRole("tab", { name: "Canvases" }));
    await user.click(screen.getByRole("button", { name: "Import JSON" }));
    const importButton = screen.getByRole("button", { name: "Import Canvas" });
    expect(importButton).toBeDisabled();

    fireEvent.change(screen.getByRole("textbox", { name: "Canvas JSON to import" }), {
      target: {
        value: JSON.stringify({
          title: 42,
          description: false,
          primary_note_id: null,
          nodes: "not-an-array",
          edges: null,
          viewport: null,
        }),
      },
    });
    await user.click(importButton);
    await waitFor(() =>
      expect(mocks.createNoteCanvas).toHaveBeenCalledWith({
        title: "Imported Canvas",
        description: undefined,
        primary_note_id: undefined,
        nodes: [],
        edges: [],
        viewport: undefined,
      }),
    );

    await user.click(screen.getByRole("button", { name: "Import JSON" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Canvas JSON to import" }), {
      target: { value: "{bad json" },
    });
    await user.click(screen.getByRole("button", { name: "Import Canvas" }));
    expect(await screen.findByText(/Unexpected token|Expected property name/)).toBeInTheDocument();

    await user.click(screen.getAllByRole("button", { name: "" })[0]);
    expect(screen.queryByRole("heading", { name: "Import Canvas JSON" })).not.toBeInTheDocument();
  });

  it("refreshes, updates, and exports content assets while exposing mutation progress", async () => {
    const user = userEvent.setup();
    const refresh = deferred<ContentAsset>();
    const ready = createContentAsset({ status: "done" });
    const review = createContentAsset({
      id: "asset-2",
      title: "Review Asset",
      status: "needs_review",
      note_id: null,
      source_pack: {},
      run_notes: null,
    });
    const inProgress = createContentAsset({
      id: "asset-3",
      title: "",
      status: "in_progress",
      source_pack: null as unknown as Record<string, unknown>,
    });
    mocks.getContentAssets.mockResolvedValue(createPaginatedResponse([ready, review, inProgress]));
    mocks.generateContentAssetSourcePack.mockReturnValue(refresh.promise);

    renderWithProviders(<NotesPage />);
    await screen.findByRole("button", { name: "Open Alpha note" });
    await user.click(screen.getByRole("tab", { name: "Content" }));
    expect(screen.getAllByText("Ready for review")).toHaveLength(2);
    expect(screen.getByText("Linked note: none")).toBeInTheDocument();
    expect(screen.getAllByText("Source docs: 0")).toHaveLength(2);

    const refreshButtons = screen.getAllByRole("button", { name: "Refresh pack" });
    await user.click(refreshButtons[0]);
    await waitFor(() => expect(refreshButtons[0]).toBeDisabled());
    expect(refreshButtons[1]).not.toBeDisabled();
    expect(mocks.generateContentAssetSourcePack).toHaveBeenCalledWith("asset-1");

    refresh.resolve(ready);
    await waitFor(() => expect(refreshButtons[0]).not.toBeDisabled());

    await user.click(screen.getAllByRole("button", { name: "done" })[1]);
    await waitFor(() =>
      expect(mocks.updateContentAsset).toHaveBeenCalledWith("asset-2", { status: "done" }),
    );

    const exportButtons = screen.getAllByRole("button", { name: "Export JSON" });
    await user.click(exportButtons[0]);
    await user.click(exportButtons[2]);
    expect(URL.createObjectURL).toHaveBeenCalledTimes(2);
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(2);
  });
});

import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent, waitFor } from "../test-utils";
import { NotesPage } from "@/pages/notes";
import { createNote, createPaginatedResponse } from "../factories";
import type { Note } from "@/types";

const mocks = vi.hoisted(() => ({
  listNotes: vi.fn(),
  getNoteGraph: vi.fn(),
  listNoteCanvases: vi.fn(),
  upsertDailyNote: vi.fn(),
  getContentAssets: vi.fn(),
}));

vi.mock("@/api/notes", () => ({
  listNotes: mocks.listNotes,
  getNoteGraph: mocks.getNoteGraph,
  listNoteCanvases: mocks.listNoteCanvases,
  upsertDailyNote: mocks.upsertDailyNote,
}));

vi.mock("@/api/content-assets", () => ({
  getContentAssets: mocks.getContentAssets,
}));

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
    <div>
      <h1>{title}</h1>
      <p>{subtitle}</p>
      <div>{children}</div>
    </div>
  ),
}));

vi.mock("@/components/ui/page-error", () => ({
  PageError: ({ message }: { message: string }) => <div>Page Error: {message}</div>,
}));

vi.mock("@/components/ui/empty-state", () => ({
  EmptyState: ({
    title,
    action,
  }: {
    title: string;
    action?: { label: string; onClick: () => void };
  }) => (
    <div>
      <div>{title}</div>
      {action ? (
        <button type="button" onClick={action.onClick}>
          {action.label}
        </button>
      ) : null}
    </div>
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
  NoteDetail: ({ noteId, onBack }: { noteId: string; onBack: () => void }) => (
    <div>
      <div>Detail {noteId}</div>
      <button type="button" onClick={onBack}>
        Back to notes
      </button>
    </div>
  ),
}));

vi.mock("@/components/notes/note-editor", () => ({
  NoteEditor: ({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) => (
    <div>
      <button type="button" onClick={onSaved}>
        Save note
      </button>
      <button type="button" onClick={onClose}>
        Close editor
      </button>
    </div>
  ),
}));

describe("NotesPage", () => {
  beforeEach(() => {
    mocks.listNotes.mockReset();
    mocks.getNoteGraph.mockReset();
    mocks.listNoteCanvases.mockReset();
    mocks.upsertDailyNote.mockReset();
    mocks.getContentAssets.mockReset();

    mocks.getNoteGraph.mockResolvedValue({ nodes: [], edges: [] });
    mocks.listNoteCanvases.mockResolvedValue(createPaginatedResponse([]));
    mocks.getContentAssets.mockResolvedValue(createPaginatedResponse([]));
    mocks.upsertDailyNote.mockResolvedValue(
      createNote({
        id: "daily-1",
        title: "Daily Note 2026-04-13",
        kind: "daily",
      }),
    );
  });

  it("renders notes, applies local filters and sorting, opens detail view, and refetches after saving", async () => {
    const user = userEvent.setup();
    const beta = createNote({
      id: "note-2",
      title: "Beta note",
      note_type: "literature",
      para_category: "project",
      created_at: "2026-04-03T09:00:00Z",
      updated_at: "2026-04-03T09:00:00Z",
    });
    const alpha = createNote({
      id: "note-1",
      title: "Alpha note",
      note_type: "permanent",
      para_category: "resource",
      created_at: "2026-04-01T09:00:00Z",
      updated_at: "2026-04-01T09:00:00Z",
    });

    mocks.listNotes.mockImplementation(
      async (params?: { kind?: string; note_type?: string; para_category?: string }) => {
        if (params?.kind === "daily" || params?.kind === "moc") {
          return createPaginatedResponse([]);
        }
        let items = [alpha, beta];
        if (params?.note_type) {
          items = items.filter((note) => note.note_type === params.note_type);
        }
        if (params?.para_category) {
          items = items.filter((note) => note.para_category === params.para_category);
        }
        return createPaginatedResponse(items);
      },
    );

    renderWithProviders(<NotesPage />);

    expect(await screen.findByRole("heading", { name: "Notes Workspace" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Open Beta note" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Open / })[0]).toHaveTextContent("Open Beta note");
    expect(mocks.listNotes).toHaveBeenCalledWith({
      limit: 100,
      search: undefined,
      note_type: undefined,
      para_category: undefined,
    });

    await user.selectOptions(screen.getAllByRole("combobox")[0], "permanent");
    expect(screen.queryByRole("button", { name: "Open Beta note" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open Alpha note" })).toBeInTheDocument();

    await user.selectOptions(screen.getAllByRole("combobox")[1], "resource");
    expect(screen.getByRole("button", { name: "Clear filters" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Sort notes" }));
    await user.click(screen.getByRole("option", { name: "Title A-Z" }));
    expect(screen.getByRole("button", { name: "Open Alpha note" })).toBeInTheDocument();

    await user.click(screen.getByText("Clear filters"));
    expect(screen.getAllByRole("button", { name: /Open / })).toHaveLength(2);

    await user.click(screen.getByRole("button", { name: "Open Alpha note" }));
    expect(await screen.findByText("Detail note-1")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Back to notes" }));
    expect(await screen.findByRole("button", { name: "Open Alpha note" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "New Note" }));
    await user.click(screen.getByRole("button", { name: "Save note" }));
    await waitFor(() => {
      expect(mocks.listNotes.mock.calls.length).toBeGreaterThan(3);
    });
  });

  it("renders the empty state when no notes exist", async () => {
    mocks.listNotes.mockImplementation(async (params?: { kind?: string }) =>
      createPaginatedResponse(params?.kind === "daily" || params?.kind === "moc" ? [] : []),
    );

    renderWithProviders(<NotesPage />);

    expect(await screen.findByText("No notes yet")).toBeInTheDocument();
  });

  it("renders the page error when note loading fails", async () => {
    mocks.listNotes.mockImplementation(async (params?: { kind?: string }) => {
      if (params?.kind === "daily" || params?.kind === "moc") {
        return createPaginatedResponse([]);
      }
      throw new Error("notes failed");
    });

    renderWithProviders(<NotesPage />);

    expect(await screen.findByText("Page Error: notes failed")).toBeInTheDocument();
  });

  it("searches with live input, shows the clear search action, and exercises all sort branches", async () => {
    const user = userEvent.setup();
    const beta = createNote({
      id: "note-2",
      title: "Beta note",
      note_type: "literature",
      para_category: "project",
      created_at: "2026-04-03T09:00:00Z",
      updated_at: "2026-04-03T09:00:00Z",
    });
    const alpha = createNote({
      id: "note-1",
      title: "Alpha note",
      note_type: "permanent",
      para_category: "resource",
      created_at: "2026-04-01T09:00:00Z",
      updated_at: "2026-04-01T09:00:00Z",
    });

    mocks.listNotes.mockImplementation(async (params?: { kind?: string; search?: string }) => {
      if (params?.kind === "daily" || params?.kind === "moc") {
        return createPaginatedResponse([]);
      }
      if (params?.search === "zzz") {
        return createPaginatedResponse([]);
      }
      return createPaginatedResponse([alpha, beta]);
    });

    renderWithProviders(<NotesPage />);

    expect(await screen.findByRole("button", { name: "Open Beta note" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Open / })[0]).toHaveTextContent("Open Beta note");

    await user.click(screen.getByRole("button", { name: "Sort notes" }));
    await user.click(screen.getByRole("option", { name: "Oldest first" }));
    expect(screen.getAllByRole("button", { name: /Open / })[0]).toHaveTextContent(
      "Open Alpha note",
    );

    await user.click(screen.getByRole("button", { name: "Sort notes" }));
    await user.click(screen.getByRole("option", { name: "Title Z-A" }));
    expect(screen.getAllByRole("button", { name: /Open / })[0]).toHaveTextContent("Open Beta note");

    await user.type(screen.getByPlaceholderText("Search notes..."), "zzz");
    expect(await screen.findByText("No notes match your search")).toBeInTheDocument();

    await user.clear(screen.getByPlaceholderText("Search notes..."));
    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: /Open / })[0]).toHaveTextContent(
        "Open Beta note",
      );
    });
  });
});

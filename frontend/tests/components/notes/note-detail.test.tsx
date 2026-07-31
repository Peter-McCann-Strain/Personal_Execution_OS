import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent, waitFor } from "../../test-utils";
import { NoteDetail } from "@/components/notes/note-detail";
import { createNote } from "../../factories";
import type { Note } from "@/types";

const mocks = vi.hoisted(() => ({
  deleteNote: vi.fn(),
  createContentAsset: vi.fn(),
  getNote: vi.fn(),
  getNoteGraph: vi.fn(),
}));

vi.mock("@/api/notes", () => ({
  deleteNote: mocks.deleteNote,
  getNote: mocks.getNote,
  getNoteGraph: mocks.getNoteGraph,
}));

vi.mock("@/api/content-assets", () => ({
  createContentAsset: mocks.createContentAsset,
}));

vi.mock("@/components/notes/linked-notes-panel", () => ({
  LinkedNotesPanel: ({
    noteId,
    onNavigate,
  }: {
    noteId: string;
    onNavigate: (noteId: string) => void;
  }) => (
    <div>
      <div>Linked panel {noteId}</div>
      <button type="button" onClick={() => onNavigate("note-2")}>
        Open linked note
      </button>
    </div>
  ),
}));

vi.mock("@/components/notes/note-editor", () => ({
  NoteEditor: ({
    note,
    onClose,
    onSaved,
  }: {
    note?: Note;
    onClose: () => void;
    onSaved: () => void;
  }) => (
    <div>
      <div>Editor for {note?.id}</div>
      <button type="button" onClick={onSaved}>
        Finish editing
      </button>
      <button type="button" onClick={onClose}>
        Close editor
      </button>
    </div>
  ),
}));

describe("NoteDetail", () => {
  beforeEach(() => {
    mocks.deleteNote.mockReset();
    mocks.createContentAsset.mockReset();
    mocks.getNote.mockReset();
    mocks.getNoteGraph.mockReset();
    mocks.getNoteGraph.mockResolvedValue({ nodes: [], edges: [] });
  });

  it("renders loading skeletons while the note query is pending", () => {
    mocks.getNote.mockReturnValue(new Promise(() => {}));

    const { container } = renderWithProviders(
      <NoteDetail noteId="note-1" onBack={vi.fn()} onNavigateNote={vi.fn()} />,
    );

    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });

  it("renders the not-found state when the note is missing", async () => {
    const onBack = vi.fn();
    mocks.getNote.mockResolvedValue(null);

    renderWithProviders(<NoteDetail noteId="note-404" onBack={onBack} onNavigateNote={vi.fn()} />);

    expect(await screen.findByText("Note not found")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Go back" }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it("renders note metadata, opens the editor, and deletes the note", async () => {
    const user = userEvent.setup();
    const onBack = vi.fn();
    const onNavigateNote = vi.fn();

    mocks.getNote.mockResolvedValue(
      createNote({
        id: "note-1",
        title: "Research note",
        content: "## Heading\n\nBody copy",
        executive_summary: "Short summary",
        source_url: "https://example.com",
        tags: ["ai", "runtime"],
      }),
    );
    mocks.deleteNote.mockResolvedValue(undefined);

    renderWithProviders(
      <NoteDetail noteId="note-1" onBack={onBack} onNavigateNote={onNavigateNote} />,
    );

    expect(await screen.findByRole("heading", { name: "Research note" })).toBeInTheDocument();
    expect(screen.getByText("Short summary")).toBeInTheDocument();
    expect(screen.getByText("Linked panel note-1")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Open linked note" }));
    expect(onNavigateNote).toHaveBeenCalledWith("note-2");

    await user.click(screen.getByRole("button", { name: "Edit" }));
    expect(await screen.findByText("Editor for note-1")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Finish editing" }));
    expect(await screen.findByRole("heading", { name: "Research note" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() => {
      expect(mocks.deleteNote).toHaveBeenCalledWith("note-1");
    });
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});

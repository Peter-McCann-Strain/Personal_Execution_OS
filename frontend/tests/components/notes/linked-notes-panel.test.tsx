import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent } from "@testing-library/react";
import { renderWithProviders, screen, waitFor } from "../../test-utils";
import { LinkedNotesPanel } from "@/components/notes/linked-notes-panel";
import { createNote } from "../../factories";
import type { LinkedNote } from "@/api/notes";

const mocks = vi.hoisted(() => ({
  getBacklinkedNotes: vi.fn(),
  createNoteLink: vi.fn(),
  getLinkedNotes: vi.fn(),
  getUnlinkedMentions: vi.fn(),
  searchNotes: vi.fn(),
}));

vi.mock("@/api/notes", () => ({
  getBacklinkedNotes: mocks.getBacklinkedNotes,
  createNoteLink: mocks.createNoteLink,
  getLinkedNotes: mocks.getLinkedNotes,
  getUnlinkedMentions: mocks.getUnlinkedMentions,
  searchNotes: mocks.searchNotes,
}));

describe("LinkedNotesPanel", () => {
  beforeEach(() => {
    mocks.getBacklinkedNotes.mockReset();
    mocks.createNoteLink.mockReset();
    mocks.getLinkedNotes.mockReset();
    mocks.getUnlinkedMentions.mockReset();
    mocks.searchNotes.mockReset();
    mocks.getBacklinkedNotes.mockResolvedValue([]);
    mocks.getUnlinkedMentions.mockResolvedValue([]);
  });

  it("renders the empty state and creates a link from search results", async () => {
    const onNavigate = vi.fn();

    mocks.getLinkedNotes.mockResolvedValue([]);
    mocks.searchNotes.mockResolvedValue([
      createNote({ id: "note-2", title: "Related note" }),
      createNote({ id: "note-1", title: "Current note" }),
    ]);
    mocks.createNoteLink.mockResolvedValue(undefined);

    renderWithProviders(<LinkedNotesPanel noteId="note-1" onNavigate={onNavigate} />);

    expect(await screen.findByText("No relationships discovered yet")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Link" }));
    fireEvent.change(screen.getByPlaceholderText("Search notes to link..."), {
      target: { value: "rel" },
    });

    expect(await screen.findByRole("button", { name: "Related note" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Current note" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Related note" }));
    fireEvent.change(screen.getByPlaceholderText("Reason for linking (optional)..."), {
      target: { value: "Shared research" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create Link" }));

    await waitFor(() => {
      expect(mocks.createNoteLink).toHaveBeenCalledWith("note-1", {
        target_note_id: "note-2",
        link_reason: "Shared research",
      });
    });
  });

  it("renders linked notes and forwards navigation", async () => {
    const linkedNote: LinkedNote = {
      ...createNote({ id: "note-2", title: "Adjacent concept" }),
      link_reason: "References the same article",
      similarity_score: 0.84,
    };

    mocks.getLinkedNotes.mockResolvedValue([linkedNote]);

    renderWithProviders(<LinkedNotesPanel noteId="note-1" onNavigate={vi.fn()} />);

    const card = await screen.findByRole("button", { name: /Adjacent concept/i });
    expect(screen.getByText("84% similar")).toBeInTheDocument();
    expect(screen.getByText("References the same article")).toBeInTheDocument();

    fireEvent.click(card);
  });

  it("renders search fallback and mutation errors inside the creator", async () => {
    mocks.getLinkedNotes.mockResolvedValue([]);
    mocks.searchNotes.mockResolvedValue([]);
    mocks.createNoteLink.mockRejectedValue(new Error("link failed"));

    renderWithProviders(<LinkedNotesPanel noteId="note-1" onNavigate={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: "Link" }));
    fireEvent.change(screen.getByPlaceholderText("Search notes to link..."), {
      target: { value: "zz" },
    });
    expect(await screen.findByText("No matching notes found")).toBeInTheDocument();

    mocks.searchNotes.mockResolvedValue([createNote({ id: "note-2", title: "Linked note" })]);
    fireEvent.change(screen.getByPlaceholderText("Search notes to link..."), {
      target: { value: "link" },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Linked note" }));
    fireEvent.click(screen.getByRole("button", { name: "Create Link" }));

    expect(await screen.findByText("link failed")).toBeInTheDocument();
  });
});

import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent, waitFor } from "../../test-utils";
import { NoteEditor } from "@/components/notes/note-editor";
import { createNote } from "../../factories";

const mocks = vi.hoisted(() => ({
  createNote: vi.fn(),
  updateNote: vi.fn(),
}));

vi.mock("@/api/notes", () => ({
  createNote: mocks.createNote,
  updateNote: mocks.updateNote,
}));

describe("NoteEditor", () => {
  beforeEach(() => {
    mocks.createNote.mockReset();
    mocks.updateNote.mockReset();
  });

  it("creates a note, normalizes tags, and closes through the backdrop", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const onSaved = vi.fn();
    const created = createNote({
      title: "Created note",
      tags: ["research", "agent"],
    });

    mocks.createNote.mockResolvedValue(created);

    renderWithProviders(<NoteEditor onClose={onClose} onSaved={onSaved} />);

    await user.type(screen.getByPlaceholderText("Note title..."), "Created note");
    await user.type(
      screen.getByPlaceholderText("Write your note... (Markdown + wiki-links supported)"),
      "Body copy",
    );
    await user.selectOptions(screen.getByDisplayValue("Fleeting"), "permanent");
    await user.selectOptions(screen.getByDisplayValue("None"), "resource");
    await user.type(screen.getByPlaceholderText("Add a tag..."), "Research");
    await user.click(screen.getByRole("button", { name: /add/i }));
    await user.type(screen.getByPlaceholderText("https://..."), "https://example.com");
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => {
      expect(mocks.createNote).toHaveBeenCalledWith({
        title: "Created note",
        content: "Body copy",
        note_type: "permanent",
        para_category: "resource",
        tags: ["research"],
        source_url: "https://example.com",
        slug: undefined,
        aliases: [],
        kind: "note",
        frontmatter: {},
      });
    });
    expect(onSaved).toHaveBeenCalledWith(created);

    const backdrop = document.querySelector(".bg-black\\/50");
    expect(backdrop).not.toBeNull();
    if (backdrop) {
      await user.click(backdrop);
    }
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("updates an existing note and supports tag removal", async () => {
    const user = userEvent.setup();
    const note = createNote({
      id: "note-9",
      title: "Existing note",
      content: "Original body",
      note_type: "literature",
      para_category: "project",
      tags: ["pkm", "reading"],
    });

    mocks.updateNote.mockResolvedValue(
      createNote({
        ...note,
        title: "Updated note",
        content: "Updated body",
        tags: ["reading"],
      }),
    );

    renderWithProviders(<NoteEditor note={note} onClose={vi.fn()} onSaved={vi.fn()} />);

    await user.clear(screen.getByPlaceholderText("Note title..."));
    await user.type(screen.getByPlaceholderText("Note title..."), "Updated note");
    await user.clear(
      screen.getByPlaceholderText("Write your note... (Markdown + wiki-links supported)"),
    );
    await user.type(
      screen.getByPlaceholderText("Write your note... (Markdown + wiki-links supported)"),
      "Updated body",
    );
    await user.click(screen.getByRole("button", { name: "Remove tag pkm" }));
    await user.click(screen.getByRole("button", { name: "Update" }));

    await waitFor(() => {
      expect(mocks.updateNote).toHaveBeenCalledWith("note-9", {
        title: "Updated note",
        content: "Updated body",
        note_type: "literature",
        para_category: "project",
        tags: ["reading"],
        source_url: undefined,
        slug: undefined,
        aliases: [],
        kind: "note",
        frontmatter: {},
      });
    });
  });

  it("renders mutation errors from failed saves", async () => {
    const user = userEvent.setup();
    mocks.createNote.mockRejectedValue(new Error("save failed"));

    renderWithProviders(<NoteEditor onClose={vi.fn()} onSaved={vi.fn()} />);

    await user.type(screen.getByPlaceholderText("Note title..."), "Failed note");
    await user.type(
      screen.getByPlaceholderText("Write your note... (Markdown + wiki-links supported)"),
      "Still tries to save",
    );
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByText("save failed")).toBeInTheDocument();
  });
});

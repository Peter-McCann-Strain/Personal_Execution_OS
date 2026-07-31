import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen } from "../../test-utils";
import { NoteCard, NoteTypeBadge } from "@/components/notes/note-card";
import { createNote } from "../../factories";

describe("NoteCard", () => {
  it("renders preview metadata and forwards selection", () => {
    const onSelect = vi.fn();
    const note = createNote({
      title: "System prompt notes",
      content: "# Heading\n\nDetailed content with [link](https://example.com)",
      source_url: "https://example.com",
      tags: ["llm", "prompting", "ops", "extra"],
    });

    renderWithProviders(<NoteCard note={note} selected onSelect={onSelect} />);

    expect(screen.getByText("System prompt notes")).toBeInTheDocument();
    expect(screen.getByText(/Heading/)).toBeInTheDocument();
    expect(screen.getByText("llm")).toBeInTheDocument();
    expect(screen.getByText("+1")).toBeInTheDocument();
    expect(
      screen.getByText(/ago|Yesterday|Today|Just now|\d{1,2}\/\d{1,2}\/\d{4}/i),
    ).toBeInTheDocument();

    screen.getByText("System prompt notes").click();
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: "note-1" }));
  });

  it("renders fallback copy when content and optional metadata are missing", () => {
    renderWithProviders(
      <NoteCard
        note={createNote({
          content: "",
          note_type: null,
          para_category: null,
          tags: [],
        })}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByText("No content")).toBeInTheDocument();
  });

  it("renders note type labels through the shared badge helper", () => {
    renderWithProviders(<NoteTypeBadge type="literature" size="md" />);

    expect(screen.getByText("Literature")).toBeInTheDocument();
  });
});

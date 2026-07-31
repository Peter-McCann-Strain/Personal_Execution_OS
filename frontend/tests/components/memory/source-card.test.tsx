import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent } from "../../test-utils";
import { SourceCard } from "@/components/memory/source-card";
import type { MemorySearchResult } from "@/types";

const mocks = vi.hoisted(() => ({
  navigate: vi.fn(),
}));

vi.mock("react-router", async () => {
  const actual = await vi.importActual<typeof import("react-router")>("react-router");
  return {
    ...actual,
    useNavigate: () => mocks.navigate,
  };
});

function createResult(overrides: Partial<MemorySearchResult> = {}): MemorySearchResult {
  return {
    content: "A".repeat(240),
    relevance_score: 0.82,
    source_id: "episode-1",
    source_type: "episode",
    ...overrides,
  };
}

describe("SourceCard", () => {
  beforeEach(() => {
    mocks.navigate.mockReset();
  });

  it("renders an episode source, supports expand/collapse, and navigates to the diary entry", async () => {
    const user = userEvent.setup();
    const { container } = renderWithProviders(<SourceCard result={createResult()} />);

    expect(screen.getByText("Episode")).toBeInTheDocument();
    expect(screen.getByText("0.82")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "View full entry" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Expand" })).toBeInTheDocument();

    const progressBar = container.querySelector(
      ".h-full.rounded-\\[var\\(--radius-full\\)\\].transition-all",
    ) as HTMLElement | null;
    expect(progressBar?.style.width).toBe("82%");

    await user.click(screen.getByRole("button", { name: "Expand" }));
    expect(screen.getByRole("button", { name: "Collapse" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "View full entry" }));
    expect(mocks.navigate).toHaveBeenCalledWith("/diary/episode-1");
  });

  it("renders note and entity sources with the correct navigation labels", async () => {
    const user = userEvent.setup();
    const { rerender } = renderWithProviders(
      <SourceCard
        result={createResult({
          content: "Note content",
          relevance_score: 0.5,
          source_id: "note-1",
          source_type: "note",
        })}
      />,
    );

    expect(screen.getByText("Note")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "View note" }));
    expect(mocks.navigate).toHaveBeenCalledWith("/notes/note-1");

    rerender(
      <SourceCard
        result={createResult({
          content: "Person entity with org context",
          relevance_score: 0.3,
          source_id: "entity-1",
          source_type: "entity",
        })}
      />,
    );

    expect(screen.getByText("Entity")).toBeInTheDocument();
    expect(screen.getByText("0.30")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "View in Knowledge Graph" }));
    expect(mocks.navigate).toHaveBeenCalledWith("/knowledge-graph?entity=entity-1");
  });

  it("falls back cleanly for unknown source types and non-person entity variants", async () => {
    const user = userEvent.setup();
    const { rerender } = renderWithProviders(
      <SourceCard
        result={createResult({
          content: "Mystery content",
          relevance_score: 0.1,
          source_id: "mystery-1",
          source_type: "mystery" as MemorySearchResult["source_type"],
        })}
      />,
    );

    expect(screen.getByText("Episode")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "View" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "View" }));
    expect(mocks.navigate).toHaveBeenCalledWith("#");

    rerender(
      <SourceCard
        result={createResult({
          content: "org chart reference",
          relevance_score: 0.2,
          source_id: "entity-org",
          source_type: "entity",
        })}
      />,
    );
    expect(screen.getByText("Entity")).toBeInTheDocument();

    rerender(
      <SourceCard
        result={createResult({
          content: "place marker reference",
          relevance_score: 0.2,
          source_id: "entity-place",
          source_type: "entity",
        })}
      />,
    );
    expect(screen.getByText("Entity")).toBeInTheDocument();

    rerender(
      <SourceCard
        result={createResult({
          content: "misc reference",
          relevance_score: 0.2,
          source_id: "entity-default",
          source_type: "entity",
        })}
      />,
    );
    expect(screen.getByText("Entity")).toBeInTheDocument();
  });
});

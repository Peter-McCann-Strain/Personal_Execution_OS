import { describe, expect, it } from "vitest";
import { renderWithProviders, screen } from "../../test-utils";
import { AnswerCard } from "@/components/memory/answer-card";
import type { MemoryAnswer } from "@/types";

function createAnswer(overrides: Partial<MemoryAnswer> = {}): MemoryAnswer {
  return {
    answer: "Use **retrieval** to ground the response.",
    confidence: 0.82,
    sources: [
      {
        content: "Diary entry content",
        relevance_score: 0.91,
        source_id: "episode-1",
        source_type: "episode",
      },
      {
        content: "Note content",
        relevance_score: 0.77,
        source_id: "note-1",
        source_type: "note",
      },
      {
        content: "Person entity",
        relevance_score: 0.55,
        source_id: "entity-1",
        source_type: "entity",
      },
    ],
    follow_up_suggestions: [],
    ...overrides,
  };
}

describe("AnswerCard", () => {
  it("renders the answer, confidence badge, and aggregated source summary", () => {
    renderWithProviders(<AnswerCard answer={createAnswer()} />);

    expect(screen.getByText("MEMORY ANSWER")).toBeInTheDocument();
    expect(screen.getByText("82% confidence")).toBeInTheDocument();
    expect(screen.getByText("retrieval")).toBeInTheDocument();
    expect(screen.getByText(/ground the response\./)).toBeInTheDocument();
    expect(screen.getByText("Sources: 1 diary entry, 1 note, 1 entity")).toBeInTheDocument();
  });

  it("renders low-confidence answers with no sources", () => {
    renderWithProviders(
      <AnswerCard
        answer={createAnswer({
          confidence: 0.25,
          sources: [],
        })}
      />,
    );

    expect(screen.getByText("25% confidence")).toBeInTheDocument();
    expect(screen.getByText("No sources")).toBeInTheDocument();
  });

  it("renders warning confidence and pluralized source groups", () => {
    renderWithProviders(
      <AnswerCard
        answer={createAnswer({
          confidence: 0.55,
          sources: [
            {
              content: "Episode A",
              relevance_score: 0.9,
              source_id: "episode-1",
              source_type: "episode",
            },
            {
              content: "Episode B",
              relevance_score: 0.8,
              source_id: "episode-2",
              source_type: "episode",
            },
            {
              content: "Entity A",
              relevance_score: 0.7,
              source_id: "entity-1",
              source_type: "entity",
            },
            {
              content: "Entity B",
              relevance_score: 0.6,
              source_id: "entity-2",
              source_type: "entity",
            },
          ],
        })}
      />,
    );

    expect(screen.getByText("55% confidence")).toBeInTheDocument();
    expect(screen.getByText("Sources: 2 diary entries, 2 entities")).toBeInTheDocument();
  });

  it("falls back to the default icon path for unknown source types", () => {
    const { container } = renderWithProviders(
      <AnswerCard
        answer={createAnswer({
          sources: [
            {
              content: "Unknown source",
              relevance_score: 0.5,
              source_id: "misc-1",
              source_type: "misc",
            },
          ],
        })}
      />,
    );

    expect(screen.getByText("No sources")).toBeInTheDocument();
    expect(container.querySelector("svg")).toBeInTheDocument();
  });
});

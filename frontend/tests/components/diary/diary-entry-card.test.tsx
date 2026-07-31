import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent } from "@testing-library/react";
import { renderWithProviders, screen } from "../../test-utils";
import { createEpisode } from "../../factories";
import { DiaryEntryCard, DiaryEntryCardSkeleton } from "@/components/diary/diary-entry-card";

describe("DiaryEntryCard", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-04-08T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders episode metadata, expands content, and forwards tag clicks", () => {
    const onTagClick = vi.fn();

    renderWithProviders(
      <DiaryEntryCard
        episode={createEpisode({
          content: "Expanded diary content.",
          summary: "Short summary",
          tags: ["focus", "work"],
          people_mentioned: ["Ada"],
          para_category: "resource",
          mood_score: 7.5,
          energy_rating: 6.5,
          created_at: "2026-04-07T12:00:00Z",
        })}
        onTagClick={onTagClick}
      />,
    );

    expect(screen.getByText("diary")).toBeInTheDocument();
    expect(screen.getByText("resource")).toBeInTheDocument();
    expect(screen.getByText("1d ago")).toBeInTheDocument();
    expect(screen.getByText("Short summary")).toBeInTheDocument();
    expect(screen.getByText("Mood 7.5")).toBeInTheDocument();
    expect(screen.getByText("Energy 6.5")).toBeInTheDocument();
    expect(screen.getByText("@Ada")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Expand" }));
    expect(screen.getByText("Expanded diary content.")).toBeInTheDocument();
    expect(screen.getByText("Source: api")).toBeInTheDocument();
    expect(screen.getByText("Source: api").parentElement).toHaveTextContent("ID: episode-");
    expect(screen.getByRole("button", { name: "Collapse" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "focus" }));
    expect(onTagClick).toHaveBeenCalledWith("focus");
  });

  it("renders fallback indicators and tag overflow for lean episodes", () => {
    renderWithProviders(
      <DiaryEntryCard
        episode={createEpisode({
          episode_type: "capture",
          summary: null,
          content: "A long lean entry for truncation.",
          para_category: null,
          mood_score: null,
          energy_rating: null,
          tags: ["one", "two", "three", "four", "five", "six"],
          people_mentioned: [],
        })}
      />,
    );

    expect(screen.getByText("capture")).toBeInTheDocument();
    expect(screen.getByText("Mood --")).toBeInTheDocument();
    expect(screen.getByText("Energy --")).toBeInTheDocument();
    expect(screen.getByText("+1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Expand" })).toBeInTheDocument();
  });

  it("covers mood and energy threshold branches across rerenders", () => {
    const { rerender } = renderWithProviders(
      <DiaryEntryCard
        episode={createEpisode({
          episode_type: "research",
          content: "Research note content.",
          summary: "Research summary",
          para_category: "project",
          tags: ["alpha"],
          mood_score: 1.5,
          energy_rating: 2.5,
        })}
      />,
    );

    expect(screen.getByText("research")).toBeInTheDocument();
    expect(screen.getByText("Mood 1.5")).toBeInTheDocument();
    expect(screen.getByText("Energy 2.5")).toBeInTheDocument();

    rerender(
      <DiaryEntryCard
        episode={createEpisode({
          episode_type: "research",
          content: "Research note content.",
          summary: "Research summary",
          para_category: "project",
          tags: ["alpha"],
          mood_score: 3.5,
          energy_rating: 5.5,
        })}
      />,
    );
    expect(screen.getByText("Mood 3.5")).toBeInTheDocument();
    expect(screen.getByText("Energy 5.5")).toBeInTheDocument();

    rerender(
      <DiaryEntryCard
        episode={createEpisode({
          episode_type: "research",
          content: "Research note content.",
          summary: "Research summary",
          para_category: "project",
          tags: ["alpha"],
          mood_score: 7.5,
          energy_rating: 8.5,
        })}
      />,
    );
    expect(screen.getByText("Mood 7.5")).toBeInTheDocument();
    expect(screen.getByText("Energy 8.5")).toBeInTheDocument();

    rerender(
      <DiaryEntryCard
        episode={createEpisode({
          episode_type: "research",
          content: "Research note content.",
          summary: "Research summary",
          para_category: "project",
          tags: ["alpha"],
          mood_score: 9.5,
          energy_rating: 9.5,
        })}
      />,
    );
    expect(screen.getByText("Mood 9.5")).toBeInTheDocument();
    expect(screen.getByText("Energy 9.5")).toBeInTheDocument();
  });

  it("allows clicking a tag without a handler", () => {
    renderWithProviders(
      <DiaryEntryCard
        episode={createEpisode({
          episode_type: "diary",
          content: "Standalone diary content.",
          summary: "Standalone summary",
          tags: ["solo"],
        })}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "solo" }));
    expect(screen.getByText("solo")).toBeInTheDocument();
  });

  it("renders the skeleton state", () => {
    const { container } = renderWithProviders(<DiaryEntryCardSkeleton />);
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });
});

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent } from "../../test-utils";
import { TutorialCard } from "@/components/tutorials/tutorial-card";
import type { Tutorial } from "@/api/tutorials";

const fixedNow = new Date("2026-04-08T12:00:00Z");

function createTutorial(overrides: Partial<Tutorial> = {}): Tutorial {
  return {
    id: "tutorial-1",
    topic: "Socratic dialogue",
    work_type: "essay",
    phase: "dialogue",
    turn_count: 4,
    bloom_start: "understand",
    bloom_end: "analyze",
    speaking_ratio_student_pct: 62,
    knowledge_gaps_found: 4,
    knowledge_gaps_addressed: 3,
    created_at: "2026-04-07T12:00:00Z",
    completed_at: null,
    ...overrides,
  };
}

describe("TutorialCard", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(fixedNow);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the tutorial summary and forwards click interactions", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const onClick = vi.fn();

    renderWithProviders(<TutorialCard tutorial={createTutorial()} onClick={onClick} />);

    expect(screen.getByText("In Progress")).toBeInTheDocument();
    expect(screen.getByText("essay")).toBeInTheDocument();
    expect(screen.getByText("Socratic dialogue")).toBeInTheDocument();
    expect(screen.getByText("1d ago")).toBeInTheDocument();
    expect(screen.getByText("Bloom Progression")).toBeInTheDocument();
    expect(screen.getByText("3/4")).toBeInTheDocument();
    expect(screen.getByText("62%")).toBeInTheDocument();
    expect(screen.getByText("Continue")).toBeInTheDocument();

    await user.click(screen.getByText("Socratic dialogue"));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("renders complete tutorials without progression metadata when absent", () => {
    renderWithProviders(
      <TutorialCard
        tutorial={createTutorial({
          phase: "complete",
          bloom_start: null,
          bloom_end: null,
          speaking_ratio_student_pct: null,
          knowledge_gaps_found: 0,
          knowledge_gaps_addressed: 0,
        })}
      />,
    );

    expect(screen.getByText("Complete")).toBeInTheDocument();
    expect(screen.getByText("View")).toBeInTheDocument();
    expect(screen.queryByText("Bloom Progression")).not.toBeInTheDocument();
    expect(screen.queryByText("62%")).not.toBeInTheDocument();
  });
});

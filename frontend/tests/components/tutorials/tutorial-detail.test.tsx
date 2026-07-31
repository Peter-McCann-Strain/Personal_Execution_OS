import { describe, expect, it } from "vitest";
import { renderWithProviders, screen, userEvent } from "../../test-utils";
import { TutorialDetailView } from "@/components/tutorials/tutorial-detail";
import type { TutorialDetail } from "@/api/tutorials";

function createDetail(overrides: Partial<TutorialDetail> = {}): TutorialDetail {
  return {
    id: "tutorial-1",
    topic: "Why do models need context?",
    work_type: "essay",
    phase: "complete",
    turn_count: 6,
    bloom_start: "understand",
    bloom_end: "evaluate",
    speaking_ratio_student_pct: 58,
    knowledge_gaps_found: 4,
    knowledge_gaps_addressed: 3,
    created_at: "2026-04-01T09:00:00Z",
    completed_at: "2026-04-03T09:00:00Z",
    submitted_work: "## Draft\n\nThe answer is layered.",
    propositions: ["Context is a budget", "Compaction is lossy"],
    transcript: [
      { speaker: "tutor", content: "Start with the budget.", turn: 1, bloom_level: "understand" },
      { speaker: "student", content: "The prompt has a budget.", turn: 2 },
    ],
    analysis: {
      bloom_progression: ["understand", "evaluate"],
      knowledge_gaps_found: 4,
      knowledge_gaps_addressed: 3,
      speaking_ratio_student_pct: 58,
      summary: "Strong framing overall.",
      strengths: ["Clear structure", "Useful examples"],
      areas_for_improvement: ["State assumptions earlier"],
    },
    ...overrides,
  };
}

describe("TutorialDetailView", () => {
  it("renders analysis, transcript, and collapsible sections", async () => {
    const user = userEvent.setup();

    renderWithProviders(<TutorialDetailView tutorial={createDetail()} />);

    expect(
      screen.getByRole("heading", { name: "Why do models need context?" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Strong framing overall.")).toBeInTheDocument();
    expect(screen.getByText("Speaking balance")).toBeInTheDocument();
    expect(screen.getByText("Student 58% / Tutor 42%")).toBeInTheDocument();
    expect(screen.getByText("Start with the budget.")).toBeInTheDocument();
    expect(screen.getByText("Bloom Level Progression")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Submitted Work" }));
    expect(await screen.findByText(/^## Draft\s+The answer is layered\.$/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Propositions (2)" }));
    expect(screen.getByText("Context is a budget")).toBeInTheDocument();

    expect(
      screen.getByRole("button", { name: "Full Transcript (2 messages)" }),
    ).toBeInTheDocument();
  });

  it("renders a lean detail view when analysis is unavailable", () => {
    renderWithProviders(
      <TutorialDetailView
        tutorial={createDetail({
          analysis: null,
          submitted_work: null,
          propositions: null,
          transcript: [],
          speaking_ratio_student_pct: null,
        })}
      />,
    );

    expect(screen.queryByText("Analysis")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Submitted Work" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Full Transcript/ })).not.toBeInTheDocument();
  });

  it("renders the detail view without a completed timestamp and toggles transcript visibility", async () => {
    const user = userEvent.setup();

    renderWithProviders(
      <TutorialDetailView
        tutorial={createDetail({
          completed_at: null,
          analysis: {
            bloom_progression: [],
            knowledge_gaps_found: 4,
            knowledge_gaps_addressed: 0,
            speaking_ratio_student_pct: null,
            summary: null,
            strengths: null,
            areas_for_improvement: null,
          },
          submitted_work: null,
          propositions: [],
          transcript: [
            {
              speaker: "tutor",
              content: "Start with the budget.",
              turn: 1,
              bloom_level: "understand",
            },
            { speaker: "student", content: "The prompt has a budget.", turn: 2 },
          ],
        })}
      />,
    );

    expect(screen.queryByText(/Completed /)).not.toBeInTheDocument();
    expect(screen.getByText("Analysis")).toBeInTheDocument();
    expect(screen.getByText("Gaps Found")).toBeInTheDocument();
    expect(screen.queryByText("Strengths")).not.toBeInTheDocument();
    expect(screen.queryByText("Areas for Improvement")).not.toBeInTheDocument();

    const transcriptToggle = screen.getByRole("button", { name: "Full Transcript (2 messages)" });
    expect(screen.getByText("Start with the budget.")).toBeInTheDocument();
    await user.click(transcriptToggle);
    expect(screen.queryByText("Start with the budget.")).not.toBeInTheDocument();
    await user.click(transcriptToggle);
    expect(screen.getByText("Start with the budget.")).toBeInTheDocument();
  });

  it("renders the minimal detail view when the tutorial has no bloom bounds or knowledge gaps", () => {
    renderWithProviders(
      <TutorialDetailView
        tutorial={createDetail({
          bloom_start: null,
          bloom_end: null,
          completed_at: null,
          knowledge_gaps_found: 0,
          knowledge_gaps_addressed: 0,
          speaking_ratio_student_pct: null,
          submitted_work: null,
          propositions: [],
          transcript: [
            { speaker: "tutor", content: "Start with context.", turn: 1 },
            { speaker: "student", content: "Keep it tight.", turn: 2 },
          ],
          analysis: {
            bloom_progression: [],
            knowledge_gaps_found: 0,
            knowledge_gaps_addressed: 0,
            speaking_ratio_student_pct: null,
            summary: null,
            strengths: null,
            areas_for_improvement: null,
          },
        })}
      />,
    );

    expect(screen.queryByText("Knowledge Assessment")).not.toBeInTheDocument();
    expect(screen.getByText("Bloom Taxonomy Progression")).toBeInTheDocument();
    expect(screen.getByText("Start with context.")).toBeInTheDocument();
    expect(screen.getByText("Keep it tight.")).toBeInTheDocument();
    expect(screen.queryByText("Strengths")).not.toBeInTheDocument();
    expect(screen.queryByText("Areas for Improvement")).not.toBeInTheDocument();
  });
});

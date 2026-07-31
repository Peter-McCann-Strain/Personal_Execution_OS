import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent } from "@testing-library/react";
import { renderWithProviders, screen, userEvent, waitFor } from "../../test-utils";
import { TutorialSession } from "@/components/tutorials/tutorial-session";
import type { TutorialDetail, TutorialTurnResponse } from "@/api/tutorials";

const mocks = vi.hoisted(() => ({
  sendTutorialTurn: vi.fn(),
  endTutorial: vi.fn(),
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: {
    error: mocks.toastError,
    success: mocks.toastSuccess,
  },
}));

vi.mock("@/api/tutorials", () => ({
  sendTutorialTurn: mocks.sendTutorialTurn,
  endTutorial: mocks.endTutorial,
}));

function createDetail(overrides: Partial<TutorialDetail> = {}): TutorialDetail {
  return {
    id: "tutorial-1",
    topic: "What is context management?",
    work_type: "essay",
    phase: "dialogue",
    turn_count: 2,
    bloom_start: "understand",
    bloom_end: "analyze",
    speaking_ratio_student_pct: 52,
    knowledge_gaps_found: 2,
    knowledge_gaps_addressed: 1,
    created_at: "2026-04-01T09:00:00Z",
    completed_at: null,
    submitted_work: "Draft",
    propositions: ["A", "B"],
    transcript: [
      { speaker: "tutor", content: "What is the budget?", turn: 1, bloom_level: "understand" },
      { speaker: "student", content: "We should keep context tight.", turn: 2 },
    ],
    analysis: {
      bloom_progression: ["understand", "analyze"],
      knowledge_gaps_found: 2,
      knowledge_gaps_addressed: 1,
      speaking_ratio_student_pct: 52,
      summary: "Keep the budget tight.",
    },
    ...overrides,
  };
}

function createTurnResponse(overrides: Partial<TutorialTurnResponse> = {}): TutorialTurnResponse {
  return {
    tutorial_id: "tutorial-1",
    content: "That is the right frame.",
    phase: "dialogue",
    speaker: "tutor",
    turn: 3,
    bloom_level: "analyze",
    analysis: {
      bloom_progression: ["understand", "analyze"],
      knowledge_gaps_found: 2,
      knowledge_gaps_addressed: 2,
      speaking_ratio_student_pct: 50,
    },
    ...overrides,
  };
}

describe("TutorialSession", () => {
  beforeEach(() => {
    mocks.sendTutorialTurn.mockReset();
    mocks.endTutorial.mockReset();
    mocks.toastError.mockReset();
    mocks.toastSuccess.mockReset();
    mocks.sendTutorialTurn.mockResolvedValue(createTurnResponse());
    mocks.endTutorial.mockResolvedValue(
      createTurnResponse({ phase: "complete", content: "Great work.", turn: 4 }),
    );
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
      cb(0);
      return 0;
    });
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: vi.fn(),
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("sends turns, appends the tutor response, and can finish the session", async () => {
    const user = userEvent.setup();
    const onBack = vi.fn();
    const onComplete = vi.fn();

    renderWithProviders(
      <TutorialSession tutorial={createDetail()} onBack={onBack} onComplete={onComplete} />,
    );

    expect(screen.getByText("What is context management?")).toBeInTheDocument();
    expect(screen.getByText("Turn 2")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Share your thinking..."), {
      target: { value: "Why keep it tight?" },
    });
    await user.click(screen.getByRole("button", { name: "Send response" }));

    await waitFor(() => {
      expect(mocks.sendTutorialTurn).toHaveBeenCalledWith("tutorial-1", "Why keep it tight?");
    });
    expect(await screen.findByText("Why keep it tight?")).toBeInTheDocument();
    expect(await screen.findByText("That is the right frame.")).toBeInTheDocument();
    expect(screen.getByText("Turn 3")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "End Tutorial" }));
    await waitFor(() => {
      expect(mocks.endTutorial).toHaveBeenCalledWith("tutorial-1");
    });
    expect(mocks.toastSuccess).toHaveBeenCalledWith("Tutorial completed");
    expect(onComplete).toHaveBeenCalledTimes(1);
  }, 10000);

  it("renders strengths and improvement areas when the analysis includes them", () => {
    renderWithProviders(
      <TutorialSession
        tutorial={createDetail({
          phase: "complete",
          transcript: [],
          analysis: {
            bloom_progression: ["understand", "analyze", "evaluate"],
            knowledge_gaps_found: 3,
            knowledge_gaps_addressed: 2,
            speaking_ratio_student_pct: 48,
            summary: "Strong conceptual framing.",
            strengths: ["Clear framing", "Good use of evidence"],
            areas_for_improvement: ["Push deeper on tradeoffs"],
          },
        })}
        onBack={vi.fn()}
        onComplete={vi.fn()}
      />,
    );

    expect(screen.getByText("Strong conceptual framing.")).toBeInTheDocument();
    expect(screen.getByText("Strengths")).toBeInTheDocument();
    expect(screen.getByText("Clear framing")).toBeInTheDocument();
    expect(screen.getByText("Areas for Improvement")).toBeInTheDocument();
    expect(screen.getByText("Push deeper on tradeoffs")).toBeInTheDocument();
  });

  it("shows a toast and restores the session when sending a turn fails", async () => {
    const user = userEvent.setup();

    mocks.sendTutorialTurn.mockRejectedValueOnce(new Error("send failed"));

    renderWithProviders(
      <TutorialSession tutorial={createDetail()} onBack={vi.fn()} onComplete={vi.fn()} />,
    );

    fireEvent.change(screen.getByPlaceholderText("Share your thinking..."), {
      target: { value: "Why keep it tight?" },
    });
    await user.click(screen.getByRole("button", { name: "Send response" }));

    await waitFor(() => {
      expect(mocks.toastError).toHaveBeenCalledWith("send failed");
    });
    expect(screen.getByText("Turn 2")).toBeInTheDocument();
    expect(screen.queryByText("Why keep it tight?")).not.toBeInTheDocument();
    expect(screen.queryByText("Thinking...")).not.toBeInTheDocument();
  });

  it("falls back to a default message when sending a turn fails without an error message", async () => {
    const user = userEvent.setup();

    mocks.sendTutorialTurn.mockRejectedValueOnce(Object.assign(new Error(""), { message: "" }));

    renderWithProviders(
      <TutorialSession tutorial={createDetail()} onBack={vi.fn()} onComplete={vi.fn()} />,
    );

    fireEvent.change(screen.getByPlaceholderText("Share your thinking..."), {
      target: { value: "Why keep it tight?" },
    });
    await user.click(screen.getByRole("button", { name: "Send response" }));

    await waitFor(() => {
      expect(mocks.toastError).toHaveBeenCalledWith("Failed to send message");
    });
  });

  it("shows a toast when ending the tutorial fails", async () => {
    const user = userEvent.setup();

    mocks.endTutorial.mockRejectedValueOnce(new Error("end failed"));

    renderWithProviders(
      <TutorialSession tutorial={createDetail()} onBack={vi.fn()} onComplete={vi.fn()} />,
    );

    await user.click(screen.getByRole("button", { name: "End Tutorial" }));

    await waitFor(() => {
      expect(mocks.toastError).toHaveBeenCalledWith("end failed");
    });
    expect(screen.getByRole("button", { name: "End Tutorial" })).toBeInTheDocument();
  });

  it("falls back to a default message when ending the tutorial fails without an error message", async () => {
    const user = userEvent.setup();

    mocks.endTutorial.mockRejectedValueOnce(Object.assign(new Error(""), { message: "" }));

    renderWithProviders(
      <TutorialSession tutorial={createDetail()} onBack={vi.fn()} onComplete={vi.fn()} />,
    );

    await user.click(screen.getByRole("button", { name: "End Tutorial" }));

    await waitFor(() => {
      expect(mocks.toastError).toHaveBeenCalledWith("Failed to end tutorial");
    });
  });

  it("ignores blank and shift-enter submits, then shows the typing indicator while a turn is pending", async () => {
    const user = userEvent.setup();
    let resolveTurn: ((value: TutorialTurnResponse) => void) | undefined;

    mocks.sendTutorialTurn.mockReturnValue(
      new Promise<TutorialTurnResponse>((resolve) => {
        resolveTurn = resolve;
      }),
    );

    renderWithProviders(
      <TutorialSession
        tutorial={createDetail({
          bloom_start: null,
          bloom_end: null,
          transcript: [],
          analysis: null,
        })}
        onBack={vi.fn()}
        onComplete={vi.fn()}
      />,
    );

    expect(screen.queryByTitle("Understand")).not.toBeInTheDocument();

    const textarea = screen.getByPlaceholderText("Share your thinking...");
    fireEvent.keyDown(textarea, { key: "Enter", code: "Enter" });
    expect(mocks.sendTutorialTurn).not.toHaveBeenCalled();

    await user.type(textarea, "Keep it moving");
    fireEvent.keyDown(textarea, { key: "Enter", code: "Enter", shiftKey: true });
    expect(mocks.sendTutorialTurn).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Send response" }));
    expect(screen.getByText("Thinking...")).toBeInTheDocument();

    resolveTurn?.(createTurnResponse({ tutorial_id: "tutorial-1" }));
    expect(await screen.findByText("That is the right frame.")).toBeInTheDocument();
  });

  it("renders the complete state without an input area", () => {
    renderWithProviders(
      <TutorialSession
        tutorial={createDetail({
          phase: "complete",
          transcript: [],
          analysis: {
            bloom_progression: ["understand", "analyze"],
            knowledge_gaps_found: 2,
            knowledge_gaps_addressed: 2,
            speaking_ratio_student_pct: 50,
            summary: "Completed.",
          },
        })}
        onBack={vi.fn()}
        onComplete={vi.fn()}
      />,
    );

    expect(screen.getByText("Complete")).toBeInTheDocument();
    expect(screen.getByText("Completed.")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Share your thinking...")).not.toBeInTheDocument();
  });

  it("handles enter-key submission without analysis updates and ends without a closing turn", async () => {
    const user = userEvent.setup();
    const onComplete = vi.fn();

    mocks.sendTutorialTurn.mockResolvedValue(
      createTurnResponse({ analysis: undefined, turn: undefined as never }),
    );
    mocks.endTutorial.mockResolvedValue(
      createTurnResponse({ content: undefined, analysis: undefined, phase: "complete", turn: 4 }),
    );

    renderWithProviders(
      <TutorialSession
        tutorial={createDetail({ analysis: null })}
        onBack={vi.fn()}
        onComplete={onComplete}
      />,
    );

    const textarea = screen.getByPlaceholderText("Share your thinking...");
    await user.type(textarea, "Keep it tighter{enter}");

    await waitFor(() => {
      expect(mocks.sendTutorialTurn).toHaveBeenCalledWith("tutorial-1", "Keep it tighter");
    });
    expect(screen.getByText("That is the right frame.")).toBeInTheDocument();
    expect(screen.queryByText("Session Analysis")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "End Tutorial" }));
    await waitFor(() => {
      expect(mocks.endTutorial).toHaveBeenCalledWith("tutorial-1");
    });
    expect(onComplete).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Great work.")).not.toBeInTheDocument();
  });
});

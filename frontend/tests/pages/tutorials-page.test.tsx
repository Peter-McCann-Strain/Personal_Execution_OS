import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent, waitFor } from "../test-utils";
import { createPaginatedResponse } from "../factories";
import { TutorialsPage } from "@/pages/tutorials";
import type { Tutorial, TutorialDetail, TutorialTurnResponse } from "@/api/tutorials";

const mocks = vi.hoisted(() => ({
  getTutorial: vi.fn(),
  getTutorials: vi.fn(),
  startTutorial: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: {
    error: mocks.toastError,
  },
}));

vi.mock("@/api/tutorials", () => ({
  getTutorial: mocks.getTutorial,
  getTutorials: mocks.getTutorials,
  startTutorial: mocks.startTutorial,
}));

vi.mock("@/components/ui/page-transition", () => ({
  PageTransition: ({ children }: { children: React.ReactNode }) => children,
}));

vi.mock("@/components/ui/page-header", () => ({
  PageHeader: ({ subtitle, title }: { subtitle: string; title: string }) => (
    <div>
      <h1>{title}</h1>
      <p>{subtitle}</p>
    </div>
  ),
}));

vi.mock("@/components/ui/page-error", () => ({
  PageError: ({ message, onRetry }: { message: string; onRetry?: () => void }) => (
    <div>
      <div>Page Error: {message}</div>
      {onRetry ? (
        <button type="button" onClick={onRetry}>
          Retry
        </button>
      ) : null}
    </div>
  ),
}));

vi.mock("@/components/ui/empty-state", () => ({
  EmptyState: ({ description, title }: { description?: string; title: string }) => (
    <div>
      <div>{title}</div>
      {description ? <div>{description}</div> : null}
    </div>
  ),
}));

vi.mock("@/components/ui/pagination", () => ({
  Pagination: ({
    onPageChange,
    page,
    totalPages,
  }: {
    onPageChange: (page: number) => void;
    page: number;
    totalPages: number;
  }) => (
    <div>
      <div>
        Page {page} of {totalPages}
      </div>
      <button type="button" onClick={() => onPageChange(page + 1)}>
        Next page
      </button>
    </div>
  ),
}));

vi.mock("@/components/tutorials/tutorial-card", () => ({
  TutorialCard: ({ onClick, tutorial }: { onClick: () => void; tutorial: Tutorial }) => (
    <div>
      <div>{tutorial.topic}</div>
      <div>{tutorial.phase}</div>
      <button type="button" onClick={onClick}>
        Open {tutorial.id}
      </button>
    </div>
  ),
}));

vi.mock("@/components/tutorials/tutorial-session", () => ({
  TutorialSession: ({
    onBack,
    onComplete,
    tutorial,
  }: {
    onBack: () => void;
    onComplete: () => void;
    tutorial: TutorialDetail;
  }) => (
    <div>
      <div>Tutorial Session: {tutorial.topic}</div>
      <button type="button" onClick={onComplete}>
        Complete session
      </button>
      <button type="button" onClick={onBack}>
        Back from session
      </button>
    </div>
  ),
}));

vi.mock("@/components/tutorials/tutorial-detail", () => ({
  TutorialDetailView: ({ tutorial }: { tutorial: TutorialDetail }) => (
    <div>Tutorial Detail: {tutorial.topic}</div>
  ),
}));

function createTutorial(overrides: Partial<Tutorial> = {}): Tutorial {
  return {
    id: "tutorial-1",
    topic: "Dependency injection",
    work_type: "essay",
    phase: "dialogue",
    turn_count: 2,
    bloom_start: "understand",
    bloom_end: "analyze",
    speaking_ratio_student_pct: 48,
    knowledge_gaps_found: 1,
    knowledge_gaps_addressed: 0,
    created_at: "2026-04-07T09:00:00Z",
    completed_at: null,
    ...overrides,
  };
}

function createTutorialDetail(overrides: Partial<TutorialDetail> = {}): TutorialDetail {
  const tutorial = createTutorial();
  return {
    ...tutorial,
    submitted_work: "Original work",
    propositions: ["One", "Two"],
    transcript: [{ speaker: "tutor", content: "Explain your premise", turn: 1 }],
    analysis: {
      bloom_progression: ["understand", "analyze"],
      knowledge_gaps_found: 1,
      knowledge_gaps_addressed: 1,
      speaking_ratio_student_pct: 50,
    },
    ...overrides,
  };
}

function createTurnResponse(overrides: Partial<TutorialTurnResponse> = {}): TutorialTurnResponse {
  return {
    tutorial_id: "tutorial-1",
    content: "Let's begin",
    phase: "dialogue",
    speaker: "tutor",
    turn: 1,
    bloom_level: "understand",
    ...overrides,
  };
}

describe("TutorialsPage", () => {
  beforeEach(() => {
    mocks.getTutorial.mockReset();
    mocks.getTutorials.mockReset();
    mocks.startTutorial.mockReset();
    mocks.startTutorial.mockResolvedValue(createTurnResponse());
    mocks.toastError.mockReset();
  });

  it("filters list items locally and paginates the tutorial query", async () => {
    const user = userEvent.setup();
    const tutorials = [
      createTutorial({ id: "tutorial-dialogue", topic: "Active tutorial", phase: "dialogue" }),
      createTutorial({
        id: "tutorial-complete",
        topic: "Completed tutorial",
        phase: "complete",
        completed_at: "2026-04-06T09:00:00Z",
      }),
      createTutorial({ id: "tutorial-submitted", topic: "Submitted tutorial", phase: "submitted" }),
    ];

    mocks.getTutorials.mockImplementation(async (params?: { limit?: number; offset?: number }) =>
      createPaginatedResponse(tutorials, {
        total: 25,
        page: params?.offset === 10 ? 2 : 1,
        page_size: 10,
        has_more: true,
      }),
    );

    renderWithProviders(<TutorialsPage />);

    expect(await screen.findByText("Active tutorial")).toBeInTheDocument();
    expect(screen.getByText("Completed tutorial")).toBeInTheDocument();
    expect(screen.getByText("Submitted tutorial")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Completed" }));
    expect(screen.getByText("Completed tutorial")).toBeInTheDocument();
    expect(screen.queryByText("Active tutorial")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => {
      expect(mocks.getTutorials).toHaveBeenLastCalledWith({ limit: 10, offset: 10 });
    });
  });

  it("opens an active tutorial session and transitions to the detail view on completion", async () => {
    const user = userEvent.setup();
    const tutorial = createTutorial({
      id: "tutorial-dialogue",
      topic: "Runtime design",
      phase: "dialogue",
    });
    const detail = createTutorialDetail({
      id: tutorial.id,
      topic: tutorial.topic,
      phase: tutorial.phase,
    });

    mocks.getTutorials.mockResolvedValue(
      createPaginatedResponse([tutorial], { total: 1, page_size: 10 }),
    );
    mocks.getTutorial.mockResolvedValue(detail);

    renderWithProviders(<TutorialsPage />);

    expect(await screen.findByText("Runtime design")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Open tutorial-dialogue" }));
    expect(await screen.findByText("Tutorial Session: Runtime design")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Complete session" }));
    expect(await screen.findByText("Tutorial Detail: Runtime design")).toBeInTheDocument();
  });

  it("renders the detail loading skeleton for completed tutorials", async () => {
    const user = userEvent.setup();
    const tutorial = createTutorial({
      id: "tutorial-complete",
      topic: "Systems thinking",
      phase: "complete",
      completed_at: "2026-04-06T09:00:00Z",
    });

    mocks.getTutorials.mockResolvedValue(
      createPaginatedResponse([tutorial], { total: 1, page_size: 10 }),
    );
    mocks.getTutorial.mockReturnValue(new Promise<TutorialDetail>(() => {}));

    const { container } = renderWithProviders(<TutorialsPage />);

    expect(await screen.findByText("Systems thinking")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Open tutorial-complete" }));
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });

  it("starts a submitted tutorial before entering the session view", async () => {
    const user = userEvent.setup();
    const tutorial = createTutorial({
      id: "tutorial-submitted",
      topic: "System design",
      phase: "submitted",
    });
    const detail = createTutorialDetail({
      id: tutorial.id,
      topic: tutorial.topic,
      phase: "dialogue",
    });

    mocks.getTutorials.mockResolvedValue(
      createPaginatedResponse([tutorial], { total: 1, page_size: 10 }),
    );
    mocks.getTutorial.mockResolvedValue(detail);
    mocks.startTutorial.mockResolvedValue(createTurnResponse({ tutorial_id: tutorial.id }));

    renderWithProviders(<TutorialsPage />);

    expect(await screen.findByText("System design")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Open tutorial-submitted" }));

    await waitFor(() => {
      expect(mocks.startTutorial).toHaveBeenCalledWith("tutorial-submitted");
    });
    expect(await screen.findByText("Tutorial Session: System design")).toBeInTheDocument();
  });

  it("shows a toast when starting a submitted tutorial fails", async () => {
    const user = userEvent.setup();
    const tutorial = createTutorial({
      id: "tutorial-submitted",
      topic: "Failure handling",
      phase: "submitted",
    });

    mocks.getTutorials.mockResolvedValue(
      createPaginatedResponse([tutorial], { total: 1, page_size: 10 }),
    );
    mocks.startTutorial.mockRejectedValue(new Error("start failed"));

    renderWithProviders(<TutorialsPage />);

    expect(await screen.findByText("Failure handling")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Open tutorial-submitted" }));

    await waitFor(() => {
      expect(mocks.toastError).toHaveBeenCalledWith("start failed");
    });
  });

  it("falls back to the default toast when starting a submitted tutorial fails without a message", async () => {
    const user = userEvent.setup();
    const tutorial = createTutorial({
      id: "tutorial-submitted",
      topic: "Fallback handling",
      phase: "submitted",
    });

    mocks.getTutorials.mockResolvedValue(
      createPaginatedResponse([tutorial], { total: 1, page_size: 10 }),
    );
    mocks.startTutorial.mockRejectedValueOnce(Object.assign(new Error(""), { message: "" }));

    renderWithProviders(<TutorialsPage />);

    expect(await screen.findByText("Fallback handling")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Open tutorial-submitted" }));

    await waitFor(() => {
      expect(mocks.toastError).toHaveBeenCalledWith("Failed to start tutorial");
    });
  });

  it("renders the page error when the tutorials list query fails", async () => {
    mocks.getTutorials.mockRejectedValue(new Error("tutorials failed"));

    renderWithProviders(<TutorialsPage />);

    expect(await screen.findByText("Page Error: tutorials failed")).toBeInTheDocument();
  });

  it("renders the fallback page error copy when the tutorials query fails without a message", async () => {
    mocks.getTutorials.mockRejectedValueOnce({});

    renderWithProviders(<TutorialsPage />);

    expect(await screen.findByText("Page Error: Failed to load tutorials")).toBeInTheDocument();
  });

  it("shows the tutorials list loading skeleton while the query is pending", () => {
    mocks.getTutorials.mockReturnValue(new Promise(() => {}));

    const { container } = renderWithProviders(<TutorialsPage />);

    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });

  it("renders the empty state when there are no tutorials", async () => {
    mocks.getTutorials.mockResolvedValue(createPaginatedResponse([], { total: 0, page_size: 10 }));

    renderWithProviders(<TutorialsPage />);

    expect(await screen.findByText("No tutorials yet")).toBeInTheDocument();
    expect(
      screen.getByText(/Submit work to start a Socratic learning session/i),
    ).toBeInTheDocument();
  });

  it("shows a page error when the selected tutorial fails to load", async () => {
    const user = userEvent.setup();
    const tutorial = createTutorial({
      id: "tutorial-dialogue",
      topic: "Runtime design",
      phase: "dialogue",
    });
    const detail = createTutorialDetail({
      id: tutorial.id,
      topic: tutorial.topic,
      phase: "dialogue",
    });

    mocks.getTutorials.mockResolvedValue(
      createPaginatedResponse([tutorial], { total: 1, page_size: 10 }),
    );
    mocks.getTutorial.mockRejectedValueOnce(new Error("detail failed"));
    mocks.getTutorial.mockResolvedValueOnce(detail);

    renderWithProviders(<TutorialsPage />);

    expect(await screen.findByText("Runtime design")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Open tutorial-dialogue" }));
    expect(await screen.findByText("Page Error: detail failed")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Tutorial Session: Runtime design")).toBeInTheDocument();
  });

  it("shows the detail error state for completed tutorials and can return to the list", async () => {
    const user = userEvent.setup();
    const tutorial = createTutorial({
      id: "tutorial-complete",
      topic: "Error states",
      phase: "complete",
      completed_at: "2026-04-06T09:00:00Z",
    });

    mocks.getTutorials.mockResolvedValue(
      createPaginatedResponse([tutorial], { total: 1, page_size: 10 }),
    );
    mocks.getTutorial.mockRejectedValueOnce(new Error("detail failed"));
    mocks.getTutorial.mockResolvedValueOnce(
      createTutorialDetail({ id: tutorial.id, topic: tutorial.topic, phase: tutorial.phase }),
    );

    renderWithProviders(<TutorialsPage />);

    expect(await screen.findByText("Error states")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Open tutorial-complete" }));
    expect(await screen.findByText("Page Error: detail failed")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Tutorial Detail: Error states")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Back to tutorials" }));
    expect(await screen.findByText("Error states")).toBeInTheDocument();
  });

  it("shows the session loading skeleton and allows retrying the list query from the error state", async () => {
    const user = userEvent.setup();
    const tutorial = createTutorial({
      id: "tutorial-dialogue",
      topic: "Runtime design",
      phase: "dialogue",
    });

    mocks.getTutorials
      .mockRejectedValueOnce(new Error("tutorials failed"))
      .mockResolvedValueOnce(createPaginatedResponse([tutorial], { total: 1, page_size: 10 }));

    let resolveDetail: ((value: TutorialDetail) => void) | undefined;
    const detailPromise = new Promise<TutorialDetail>((resolve) => {
      resolveDetail = resolve;
    });
    mocks.getTutorial.mockReturnValue(detailPromise);

    const { container } = renderWithProviders(<TutorialsPage />);

    expect(await screen.findByText("Page Error: tutorials failed")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Runtime design")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Open tutorial-dialogue" }));
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);

    resolveDetail?.(
      createTutorialDetail({ id: tutorial.id, topic: tutorial.topic, phase: "dialogue" }),
    );
    expect(await screen.findByText("Tutorial Session: Runtime design")).toBeInTheDocument();
  });
});

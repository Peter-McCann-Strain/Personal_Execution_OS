import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent, waitFor } from "../test-utils";
import { MemoryPage } from "@/pages/memory";
import type { MemoryAnswer } from "@/types";

const mocks = vi.hoisted(() => ({
  searchMemory: vi.fn(),
  listSavedMemories: vi.fn(),
  createSavedMemory: vi.fn(),
  updateSavedMemory: vi.fn(),
  deleteSavedMemory: vi.fn(),
  mergeSavedMemories: vi.fn(),
}));

vi.mock("@/api/memory", () => ({
  searchMemory: mocks.searchMemory,
}));

vi.mock("@/api/saved-memories", () => ({
  listSavedMemories: mocks.listSavedMemories,
  createSavedMemory: mocks.createSavedMemory,
  updateSavedMemory: mocks.updateSavedMemory,
  deleteSavedMemory: mocks.deleteSavedMemory,
  mergeSavedMemories: mocks.mergeSavedMemories,
}));

vi.mock("@/components/ui/page-transition", () => ({
  PageTransition: ({ children }: { children: React.ReactNode }) => children,
}));

vi.mock("@/components/ui/page-error", () => ({
  PageError: ({ message, onRetry }: { message: string; onRetry: () => void }) => (
    <div>
      <div>Page Error: {message}</div>
      <button type="button" onClick={onRetry}>
        Retry search
      </button>
    </div>
  ),
}));

vi.mock("@/components/memory/answer-card", () => ({
  AnswerCard: ({ answer }: { answer: MemoryAnswer }) => <div>Answer: {answer.answer}</div>,
}));

vi.mock("@/components/memory/source-card", () => ({
  SourceCard: ({ result }: { result: MemoryAnswer["sources"][number] }) => (
    <div>Source: {result.source_id}</div>
  ),
}));

vi.mock("@/components/memory/follow-up-pills", () => ({
  FollowUpPills: ({
    onSelect,
    suggestions,
  }: {
    onSelect: (query: string) => void;
    suggestions: string[];
  }) => (
    <div>
      {suggestions.map((suggestion) => (
        <button key={suggestion} type="button" onClick={() => onSelect(suggestion)}>
          Follow up: {suggestion}
        </button>
      ))}
    </div>
  ),
}));

function createAnswer(overrides: Partial<MemoryAnswer> = {}): MemoryAnswer {
  return {
    answer: "Ground the answer with retrieved context.",
    confidence: 0.86,
    sources: [
      {
        title: "Diary result",
        content: "Diary result",
        relevance_score: 0.9,
        source_id: "episode-1",
        source_type: "episode",
        source_label: "Recent chat",
        source_url: null,
        provenance_label: "Conversation history",
      },
    ],
    follow_up_suggestions: ["What changed this week?"],
    ...overrides,
  };
}

describe("MemoryPage", () => {
  beforeEach(() => {
    mocks.searchMemory.mockReset();
    mocks.listSavedMemories.mockReset();
    mocks.createSavedMemory.mockReset();
    mocks.updateSavedMemory.mockReset();
    mocks.deleteSavedMemory.mockReset();
    mocks.mergeSavedMemories.mockReset();
    mocks.listSavedMemories.mockResolvedValue({
      items: [
        {
          id: "memory-1",
          user_id: "owner",
          title: "Writing tone",
          content: "Direct and concise.",
          scope: "global",
          scope_key: null,
          state: "active",
          source_type: "manual",
          source_id: null,
          provenance: { created_via: "control_center" },
          pinned: false,
          auto_captured: false,
          last_used_at: null,
          last_confirmed_at: null,
          created_at: "2026-04-13T09:00:00Z",
          updated_at: "2026-04-13T09:00:00Z",
        },
        {
          id: "memory-2",
          user_id: "owner",
          title: "Weekly summaries",
          content: "Keep them brief.",
          scope: "global",
          scope_key: null,
          state: "active",
          source_type: "manual",
          source_id: null,
          provenance: { created_via: "control_center" },
          pinned: false,
          auto_captured: false,
          last_used_at: null,
          last_confirmed_at: null,
          created_at: "2026-04-13T09:00:00Z",
          updated_at: "2026-04-13T09:00:00Z",
        },
      ],
      total: 2,
      offset: 0,
      limit: 12,
      has_more: false,
    });
  });

  it("renders the empty state before any search", () => {
    renderWithProviders(<MemoryPage />);

    expect(screen.getByRole("heading", { name: "Memory Search" })).toBeInTheDocument();
    expect(
      screen.getByText("Ask me anything about your notes, diary, or knowledge base."),
    ).toBeInTheDocument();
  });

  it("searches, renders results, and allows follow-up queries", async () => {
    const user = userEvent.setup();
    mocks.searchMemory.mockResolvedValueOnce(createAnswer()).mockResolvedValueOnce(
      createAnswer({
        answer: "The follow-up answer is ready.",
        follow_up_suggestions: [],
      }),
    );

    renderWithProviders(<MemoryPage />);

    await user.type(
      screen.getByPlaceholderText("Ask anything about your notes, diary, or knowledge..."),
      "Summarize my recent notes",
    );
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(
      await screen.findByText("Answer: Ground the answer with retrieved context."),
    ).toBeInTheDocument();
    expect(screen.getByText("Source: episode-1")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Follow up: What changed this week?" }));

    await waitFor(() => {
      expect(mocks.searchMemory.mock.calls[0]?.[0]).toEqual({
        query: "Summarize my recent notes",
        sensitive_mode: false,
        suppressed_sources: [],
      });
      expect(mocks.searchMemory.mock.calls[1]?.[0]).toEqual({
        query: "What changed this week?",
        sensitive_mode: false,
        suppressed_sources: [],
      });
    });
    expect(await screen.findByText("Answer: The follow-up answer is ready.")).toBeInTheDocument();
  });

  it("shows the no-results state when search returns no sources", async () => {
    const user = userEvent.setup();
    mocks.searchMemory.mockResolvedValue(
      createAnswer({
        sources: [],
        follow_up_suggestions: [],
      }),
    );

    renderWithProviders(<MemoryPage />);

    await user.type(
      screen.getByPlaceholderText("Ask anything about your notes, diary, or knowledge..."),
      "Unknown topic",
    );
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByText('Nothing found for "Unknown topic"')).toBeInTheDocument();
  });

  it("shows the loading and error states and retries the last query", async () => {
    const user = userEvent.setup();
    let rejectSearch: ((error: Error) => void) | null = null;
    mocks.searchMemory
      .mockImplementationOnce(
        () =>
          new Promise<MemoryAnswer>((_, reject) => {
            rejectSearch = reject;
          }),
      )
      .mockResolvedValueOnce(createAnswer());

    renderWithProviders(<MemoryPage />);

    await user.type(
      screen.getByPlaceholderText("Ask anything about your notes, diary, or knowledge..."),
      "Retry me",
    );
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(document.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);

    rejectSearch?.(new Error("memory failed"));

    expect(await screen.findByText("Page Error: memory failed")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry search" }));
    await waitFor(() => {
      expect(mocks.searchMemory.mock.calls[0]?.[0]).toEqual({
        query: "Retry me",
        sensitive_mode: false,
        suppressed_sources: [],
      });
      expect(mocks.searchMemory.mock.calls[1]?.[0]).toEqual({
        query: "Retry me",
        sensitive_mode: false,
        suppressed_sources: [],
      });
    });
  });

  it("allows selecting memories for merge", async () => {
    const user = userEvent.setup();
    renderWithProviders(<MemoryPage />);

    expect(await screen.findByText("Memory Control Center")).toBeInTheDocument();
    expect(await screen.findByText("Writing tone")).toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "Select" })[0]);
    await user.click(screen.getAllByRole("button", { name: "Select" })[0]);

    expect(await screen.findByText("2 selected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Merge selected" })).toBeInTheDocument();
  });
});

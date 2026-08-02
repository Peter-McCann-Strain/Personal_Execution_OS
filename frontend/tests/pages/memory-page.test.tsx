import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent, waitFor, within } from "../test-utils";
import { MemoryPage } from "@/pages/memory";
import type { MemoryAnswer, SavedMemory } from "@/types";

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

function createSavedMemory(overrides: Partial<SavedMemory> = {}): SavedMemory {
  return {
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
    mocks.createSavedMemory.mockResolvedValue(createSavedMemory({ id: "created-memory" }));
    mocks.updateSavedMemory.mockResolvedValue(createSavedMemory());
    mocks.deleteSavedMemory.mockResolvedValue(undefined);
    mocks.mergeSavedMemories.mockResolvedValue(createSavedMemory());
    mocks.listSavedMemories.mockResolvedValue({
      items: [
        createSavedMemory(),
        createSavedMemory({
          id: "memory-2",
          title: "Weekly summaries",
          content: "Keep them brief.",
        }),
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
    await user.click(screen.getByRole("button", { name: "Merge selected" }));

    await waitFor(() => {
      expect(mocks.mergeSavedMemories).toHaveBeenCalledWith({
        target_memory_id: "memory-1",
        source_memory_ids: ["memory-2"],
      });
    });
    expect(screen.queryByText("2 selected")).not.toBeInTheDocument();
  });

  it("applies privacy controls to searches and can restore a suppressed source", async () => {
    const user = userEvent.setup();
    mocks.searchMemory.mockResolvedValue(createAnswer());

    renderWithProviders(<MemoryPage />);

    await user.click(screen.getByRole("button", { name: "Sensitive mode" }));
    await user.click(screen.getByRole("button", { name: "Saved memories" }));
    await user.click(screen.getByRole("button", { name: "Connector data" }));
    await user.click(screen.getByRole("button", { name: "Show Saved memories" }));

    await user.type(
      screen.getByPlaceholderText("Ask anything about your notes, diary, or knowledge..."),
      "Private context",
    );
    await user.keyboard("{Enter}");

    await waitFor(() => {
      expect(mocks.searchMemory.mock.calls[0]?.[0]).toEqual({
        query: "Private context",
        sensitive_mode: true,
        suppressed_sources: ["connector_document"],
      });
    });
    expect(screen.getByRole("button", { name: "Sensitive mode on" })).toBeInTheDocument();
  });

  it("creates an explicit memory and clears the form after success", async () => {
    const user = userEvent.setup();
    renderWithProviders(<MemoryPage />);

    await screen.findByText("Memory Control Center");
    const title = screen.getByPlaceholderText("Prefers concise weekly summaries");
    const content = screen.getByPlaceholderText(
      "Use short executive summaries unless I ask for detail.",
    );

    await user.type(title, "Decision style");
    await user.type(content, "Show the trade-offs before recommending.");
    await user.click(screen.getByRole("button", { name: "Save memory" }));

    await waitFor(() => {
      expect(mocks.createSavedMemory).toHaveBeenCalledWith({
        title: "Decision style",
        content: "Show the trade-offs before recommending.",
        scope: "global",
        source_type: "manual",
      });
    });
    expect(title).toHaveValue("");
    expect(content).toHaveValue("");
  });

  it("edits a memory and sends each lifecycle action to the API", async () => {
    const user = userEvent.setup();
    renderWithProviders(<MemoryPage />);

    const content = await screen.findByText("Direct and concise.");
    const card = content.parentElement;
    expect(card).not.toBeNull();
    const controls = within(card!);

    await user.click(controls.getByRole("button", { name: "Edit" }));
    await user.clear(controls.getByRole("textbox", { name: "Memory title" }));
    await user.type(controls.getByRole("textbox", { name: "Memory title" }), "Updated tone");
    await user.selectOptions(controls.getByRole("combobox", { name: "Memory scope" }), "project");
    const textboxes = controls.getAllByRole("textbox");
    const contentEditor = textboxes.find(
      (textbox) => textbox.getAttribute("aria-label") !== "Memory title",
    );
    expect(contentEditor).toBeDefined();
    await user.clear(contentEditor!);
    await user.type(contentEditor!, "Use the shortest useful answer.");
    await user.click(controls.getByRole("button", { name: "Save edit" }));

    await waitFor(() => {
      expect(mocks.updateSavedMemory).toHaveBeenCalledWith("memory-1", {
        title: "Updated tone",
        content: "Use the shortest useful answer.",
        scope: "project",
      });
    });

    for (const [name, data] of [
      ["Pin", { pinned: true }],
      ["Mark used", { mark_used: true }],
      ["Snooze", { state: "snoozed" }],
      ["Archive", { state: "archived" }],
      ["Confirm", { confirm_now: true }],
    ] as const) {
      await user.click(controls.getByRole("button", { name }));
      await waitFor(() => {
        expect(mocks.updateSavedMemory).toHaveBeenCalledWith("memory-1", data);
      });
    }

    await user.click(controls.getByRole("button", { name: "Forget" }));
    await waitFor(() => {
      expect(mocks.deleteSavedMemory).toHaveBeenCalledWith("memory-1");
    });
  });

  it("renders retained provenance and restores pinned, snoozed, and archived memories", async () => {
    const user = userEvent.setup();
    mocks.listSavedMemories.mockResolvedValue({
      items: [
        createSavedMemory({
          pinned: true,
          state: "snoozed",
          last_confirmed_at: "2026-04-13T09:00:00Z",
          last_used_at: "2026-04-14T09:00:00Z",
          provenance: {
            created_via: "migration",
            merged_from_titles: ["Old tone", "Earlier style"],
          },
        }),
        createSavedMemory({
          id: "memory-archived",
          title: "Archived preference",
          content: "Old preference",
          state: "archived",
          source_type: null,
          provenance: {},
        }),
      ],
      total: 2,
      offset: 0,
      limit: 12,
      has_more: false,
    });

    renderWithProviders(<MemoryPage />);

    const firstContent = await screen.findByText("Direct and concise.");
    const firstCard = within(firstContent.parentElement!);
    expect(firstCard.getByText("Pinned")).toBeInTheDocument();
    expect(firstCard.getByText("merged: 2")).toBeInTheDocument();
    expect(firstCard.getByText(/confirmed/)).toBeInTheDocument();
    expect(firstCard.getByText(/^used /)).toBeInTheDocument();

    await user.click(firstCard.getByRole("button", { name: "Unpin" }));
    await user.click(firstCard.getByRole("button", { name: "Unsnooze" }));
    const archivedCard = within((await screen.findByText("Old preference")).parentElement!);
    await user.click(archivedCard.getByRole("button", { name: "Restore" }));

    await waitFor(() => {
      expect(mocks.updateSavedMemory).toHaveBeenCalledWith("memory-1", { pinned: false });
      expect(mocks.updateSavedMemory).toHaveBeenCalledWith("memory-1", { state: "active" });
      expect(mocks.updateSavedMemory).toHaveBeenCalledWith("memory-archived", { state: "active" });
    });
  });

  it("clears a selection without merging and cancels an edit", async () => {
    const user = userEvent.setup();
    renderWithProviders(<MemoryPage />);

    await screen.findByText("Writing tone");
    await user.click(screen.getAllByRole("button", { name: "Select" })[0]);
    expect(screen.getByText("1 selected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Merge selected" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.queryByText("1 selected")).not.toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "Select" })[0]);
    await user.click(screen.getByRole("button", { name: "Selected" }));
    expect(screen.queryByText("1 selected")).not.toBeInTheDocument();

    const card = within(screen.getByText("Direct and concise.").parentElement!);
    await user.click(card.getByRole("button", { name: "Edit" }));
    await user.click(card.getByRole("button", { name: "Cancel" }));
    expect(card.getByRole("button", { name: "Edit" })).toBeInTheDocument();
  });
});

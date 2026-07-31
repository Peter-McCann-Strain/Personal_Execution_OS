import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent } from "../../test-utils";
import { ContextInspector } from "@/components/monitoring/context-inspector";

const mocks = vi.hoisted(() => ({
  inspectChatContext: vi.fn(),
}));

vi.mock("@/api/chat", () => ({
  inspectChatContext: mocks.inspectChatContext,
}));

describe("ContextInspector", () => {
  beforeEach(() => {
    mocks.inspectChatContext.mockReset();
  });

  it("renders an inspection result with memory candidates and section breakdown", async () => {
    const user = userEvent.setup();
    mocks.inspectChatContext.mockResolvedValueOnce({
      request_id: "ctx-1",
      inspection: {
        engine: "hierarchical",
        historySummarized: true,
        prunedMessages: 3,
        prunedCharacters: 128,
        durableMemoryCandidates: [
          {
            category: "preference",
            excerpt: "Prefer concise updates over long summaries.",
            sourceRole: "memory",
          },
        ],
        ragChunksIncluded: 2,
        ragChunksFiltered: 5,
        totalTokensEstimate: 1800,
        sections: [
          { name: "system", tokens: 240, itemCount: 1, present: true },
          { name: "working", tokens: 700, itemCount: 4, present: true },
          { name: "summary", tokens: 180, itemCount: null, present: false },
        ],
      },
    });

    renderWithProviders(<ContextInspector />);

    await user.click(screen.getByRole("button", { name: "Inspect Context" }));

    expect(await screen.findByText("Total Budget")).toBeInTheDocument();
    expect(screen.getByText("1800")).toBeInTheDocument();
    expect(screen.getByText("Pruned")).toBeInTheDocument();
    expect(screen.getByText("128 chars removed")).toBeInTheDocument();
    expect(screen.getByText("Durable Candidates")).toBeInTheDocument();
    expect(screen.getByText("Prefer concise updates over long summaries.")).toBeInTheDocument();
    expect(screen.getByText("system")).toBeInTheDocument();
    expect(screen.getByText("Included · 1 item(s)")).toBeInTheDocument();
    expect(screen.getByText("Omitted")).toBeInTheDocument();
  });

  it("keeps the inspect button disabled for blank drafts and shows the empty candidate state", async () => {
    const user = userEvent.setup();
    mocks.inspectChatContext.mockResolvedValueOnce({
      request_id: "ctx-2",
      inspection: {
        engine: "hierarchical",
        historySummarized: false,
        prunedMessages: 0,
        prunedCharacters: 0,
        durableMemoryCandidates: [],
        ragChunksIncluded: 0,
        ragChunksFiltered: 0,
        totalTokensEstimate: 900,
        sections: [{ name: "system", tokens: 240, itemCount: 1, present: true }],
      },
    });

    renderWithProviders(<ContextInspector />);

    const textarea = screen.getByPlaceholderText(
      "Type a message to inspect its assembled context...",
    );

    await user.clear(textarea);
    await user.type(textarea, "   ");

    expect(screen.getByRole("button", { name: "Inspect Context" })).toBeDisabled();

    await user.clear(textarea);
    await user.type(textarea, "show me the context");
    await user.click(screen.getByRole("button", { name: "Inspect Context" }));

    expect(
      await screen.findByText("No durable memory candidates were detected for this prompt."),
    ).toBeInTheDocument();
  });

  it("surfaces mutation failures from the backend inspector", async () => {
    const user = userEvent.setup();
    mocks.inspectChatContext.mockRejectedValueOnce(new Error("context inspection failed"));

    renderWithProviders(<ContextInspector />);

    await user.click(screen.getByRole("button", { name: "Inspect Context" }));

    expect(await screen.findByText("context inspection failed")).toBeInTheDocument();
  });
});

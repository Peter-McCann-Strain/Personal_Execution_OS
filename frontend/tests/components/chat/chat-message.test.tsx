import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent } from "../../test-utils";
import { ChatMessage } from "@/components/chat/chat-message";
import type { ChatMessage as ChatMessageType } from "@/types";

function makeMessage(
  overrides: Partial<ChatMessageType> &
    Pick<ChatMessageType, "id" | "role" | "content" | "timestamp">,
): ChatMessageType {
  return {
    agent: undefined,
    metadata: undefined,
    isStreaming: false,
    ...overrides,
  };
}

describe("ChatMessage", () => {
  const originalScrollIntoView = HTMLElement.prototype.scrollIntoView;
  const scrollIntoViewMock = vi.fn();

  beforeEach(() => {
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoViewMock,
    });
    scrollIntoViewMock.mockReset();
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
      cb(0);
      return 0;
    });
  });

  afterEach(() => {
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: originalScrollIntoView,
    });
    vi.unstubAllGlobals();
  });

  it("renders system messages as centered status text", () => {
    renderWithProviders(
      <ChatMessage
        message={makeMessage({
          id: "system-1",
          role: "system",
          content: "System maintenance completed",
          timestamp: "2026-04-07T12:00:00.000Z",
        })}
      />,
    );

    expect(screen.getByText("System maintenance completed")).toBeInTheDocument();
  });

  it("renders user messages with relative time metadata", () => {
    renderWithProviders(
      <ChatMessage
        message={makeMessage({
          id: "user-1",
          role: "user",
          content: "Can you help me?",
          timestamp: new Date().toISOString(),
        })}
      />,
    );

    expect(screen.getByText("Can you help me?")).toBeInTheDocument();
    expect(screen.getByText("just now")).toBeInTheDocument();
  });

  it("renders assistant markdown, fallback agent label, and streaming cursor", () => {
    const markdown = [
      "# Heading",
      "",
      "## Section",
      "",
      "### Detail",
      "",
      "Paragraph with **bold** text, [link](https://example.com) and `inline`.",
      "",
      "- One",
      "- Two",
      "",
      "1. First",
      "2. Second",
      "",
      "> Quoted",
      "",
      "---",
      "",
      "```ts",
      "const x = 1;",
      "```",
      "",
      "| A | B |",
      "| --- | --- |",
      "| 1 | 2 |",
    ].join("\n");

    const { container } = renderWithProviders(
      <ChatMessage
        message={makeMessage({
          id: "assistant-1",
          role: "assistant",
          content: markdown,
          timestamp: "2026-04-07T11:59:00.000Z",
          isStreaming: true,
        })}
      />,
    );

    expect(screen.getByText("Assistant")).toBeInTheDocument();
    expect(screen.getByText("Heading")).toBeInTheDocument();
    expect(screen.getByText("Section")).toBeInTheDocument();
    expect(screen.getByText("Detail")).toBeInTheDocument();
    expect(screen.getByText("bold")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "link" })).toHaveAttribute(
      "href",
      "https://example.com",
    );
    expect(screen.getByText("One")).toBeInTheDocument();
    expect(screen.getByText("First")).toBeInTheDocument();
    expect(screen.getByText("Quoted")).toBeInTheDocument();
    expect(screen.getByText("const x = 1;")).toBeInTheDocument();
    expect(container.querySelector(".animate-pulse")).toBeInTheDocument();
  });

  it("renders agent badges and expandable tool calls", async () => {
    const user = userEvent.setup();

    renderWithProviders(
      <ChatMessage
        message={makeMessage({
          id: "assistant-2",
          role: "assistant",
          agent: "review",
          content: "Done",
          timestamp: "2026-04-07T11:55:00.000Z",
          metadata: {
            tool_calls: [
              { name: "search", result: "Found two matches" },
              { result: "Fallback result" },
              "legacy-call",
            ],
          },
        })}
      />,
    );

    expect(screen.getAllByText("review")[0]).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "search" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "unknown" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "legacy-call" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "search" }));
    expect(screen.getByText("Found two matches")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "unknown" }));
    expect(screen.getByText("Fallback result")).toBeInTheDocument();
  });

  it("renders supporting context citations when present", () => {
    renderWithProviders(
      <ChatMessage
        message={makeMessage({
          id: "assistant-3",
          role: "assistant",
          agent: "memory",
          content: "Here is the answer.",
          timestamp: "2026-04-07T11:52:00.000Z",
          metadata: {
            citations: [
              {
                source_id: "note-1",
                source_type: "note",
                label: "Launch prep note",
                excerpt: "Detailed launch prep checklist",
                url: "https://example.com/note-1",
              },
            ],
          },
        })}
      />,
    );

    expect(screen.getByRole("link", { name: /launch prep note/i })).toHaveAttribute(
      "href",
      "https://example.com/note-1",
    );
    expect(screen.getByText("Detailed launch prep checklist")).toBeInTheDocument();
  });
});

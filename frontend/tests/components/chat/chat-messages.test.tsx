import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent } from "@testing-library/react";
import { renderWithProviders, screen, userEvent } from "../../test-utils";
import { ChatMessages } from "@/components/chat/chat-messages";
import type { ChatMessage } from "@/types";

function makeMessage(
  overrides: Partial<ChatMessage> & Pick<ChatMessage, "id" | "role" | "content" | "timestamp">,
): ChatMessage {
  return {
    agent: undefined,
    metadata: undefined,
    isStreaming: false,
    ...overrides,
  };
}

describe("ChatMessages", () => {
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
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("renders the empty state and allows suggested prompts to be sent", async () => {
    const user = userEvent.setup();
    const onSendPrompt = vi.fn();

    renderWithProviders(
      <ChatMessages messages={[]} isStreaming={false} onSendPrompt={onSendPrompt} />,
    );

    expect(screen.getByText("How can I help?")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "How am I feeling this week?" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Summarise my open commitments" }));
    expect(onSendPrompt).toHaveBeenCalledWith("Summarise my open commitments");
  });

  it("groups messages by day labels and shows the streaming indicator", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-04-07T12:00:00.000Z"));
    const oldLabelSpy = vi
      .spyOn(Date.prototype, "toLocaleDateString")
      .mockReturnValue("Older date");

    const messages: ChatMessage[] = [
      makeMessage({
        id: "today-2",
        role: "assistant",
        agent: "review",
        content: "Another today message",
        timestamp: "2026-04-07T10:30:00.000Z",
      }),
      makeMessage({
        id: "today",
        role: "user",
        content: "Today message",
        timestamp: "2026-04-07T09:00:00.000Z",
      }),
      makeMessage({
        id: "yesterday",
        role: "assistant",
        agent: "review",
        content: "Yesterday message",
        timestamp: "2026-04-06T18:00:00.000Z",
      }),
      makeMessage({
        id: "older",
        role: "assistant",
        agent: "diary",
        content: "Older message",
        timestamp: "2026-03-28T12:00:00.000Z",
      }),
    ];

    renderWithProviders(<ChatMessages messages={messages} isStreaming={true} />);

    scrollIntoViewMock.mockClear();
    await Promise.resolve();
    expect(screen.getByText("Today")).toBeInTheDocument();
    expect(screen.getByText("Yesterday")).toBeInTheDocument();
    expect(screen.getAllByText("Older date")[0]).toBeInTheDocument();
    expect(screen.getByText("Today message")).toBeInTheDocument();
    expect(screen.getByText("Another today message")).toBeInTheDocument();
    expect(screen.getByText("Yesterday message")).toBeInTheDocument();
    expect(screen.getByText("Older message")).toBeInTheDocument();
    expect(screen.getByLabelText("Processing")).toBeInTheDocument();

    oldLabelSpy.mockRestore();
    vi.useRealTimers();
  });

  it("shows a scroll-to-bottom button when the list is scrolled away", async () => {
    const user = userEvent.setup();
    const messages = [
      makeMessage({
        id: "message-1",
        role: "assistant",
        agent: "review",
        content: "Message",
        timestamp: "2026-04-07T11:55:00.000Z",
      }),
    ];

    const { container } = renderWithProviders(
      <ChatMessages messages={messages} isStreaming={false} />,
    );

    scrollIntoViewMock.mockClear();

    const scroller = container.firstElementChild as HTMLDivElement;
    Object.defineProperty(scroller, "scrollHeight", { configurable: true, value: 1000 });
    Object.defineProperty(scroller, "clientHeight", { configurable: true, value: 300 });
    Object.defineProperty(scroller, "scrollTop", { configurable: true, value: 0, writable: true });

    fireEvent.scroll(scroller);

    const button = screen.getByRole("button", { name: /new messages/i });
    expect(button).toBeInTheDocument();

    await user.click(button);
    expect(scrollIntoViewMock).toHaveBeenCalled();
  });
});

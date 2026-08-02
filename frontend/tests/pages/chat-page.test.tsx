import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";
import { render, screen } from "@testing-library/react";
import { renderWithProviders, userEvent, waitFor } from "../test-utils";
import { ChatPage } from "@/pages/chat";

const mocks = vi.hoisted(() => ({
  useChat: vi.fn(),
  chatMessages: vi.fn(),
  chatInput: vi.fn(),
}));

vi.mock("@/hooks/use-chat", () => ({
  useChat: mocks.useChat,
}));

vi.mock("@/components/chat/chat-messages", () => ({
  ChatMessages: (props: unknown) => {
    mocks.chatMessages(props);
    return <div data-testid="chat-messages">ChatMessages</div>;
  },
}));

vi.mock("@/components/chat/chat-input", () => ({
  ChatInput: (props: unknown) => {
    mocks.chatInput(props);
    return <div data-testid="chat-input">ChatInput</div>;
  },
}));

vi.mock("@/components/ui/page-transition", () => ({
  PageTransition: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

describe("ChatPage", () => {
  beforeEach(() => {
    mocks.chatMessages.mockReset();
    mocks.chatInput.mockReset();
    mocks.useChat.mockReturnValue({
      messages: [
        {
          id: "user-1",
          role: "user",
          content: "Plan my day",
          timestamp: new Date().toISOString(),
        },
      ],
      isStreaming: true,
      inputValue: "Draft reply",
      setInputValue: vi.fn(),
      sendMessage: vi.fn(),
      stopStreaming: vi.fn(),
      sensitiveMode: false,
      suppressedSources: [],
      toggleSensitiveMode: vi.fn(),
      toggleSuppressedSource: vi.fn(),
    });
  });

  it("renders chat messages and input using useChat state", () => {
    renderWithProviders(<ChatPage />);

    expect(screen.getByTestId("chat-messages")).toBeInTheDocument();
    expect(screen.getByTestId("chat-input")).toBeInTheDocument();
    expect(screen.getByText("Memory controls")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sensitive mode" })).toBeInTheDocument();

    expect(mocks.chatMessages).toHaveBeenCalledWith(
      expect.objectContaining({
        messages: expect.arrayContaining([
          expect.objectContaining({
            role: "user",
            content: "Plan my day",
          }),
        ]),
        isStreaming: true,
      }),
    );

    expect(mocks.chatInput).toHaveBeenCalledWith(
      expect.objectContaining({
        value: "Draft reply",
        isStreaming: true,
        onChange: expect.any(Function),
        onSend: expect.any(Function),
        onStop: expect.any(Function),
      }),
    );
  });

  it("consumes a prompt deep link and forwards privacy-control actions", async () => {
    const user = userEvent.setup();
    const setInputValue = vi.fn();
    const toggleSensitiveMode = vi.fn();
    const toggleSuppressedSource = vi.fn();
    mocks.useChat.mockReturnValue({
      messages: [],
      isStreaming: false,
      inputValue: "",
      setInputValue,
      sendMessage: vi.fn(),
      stopStreaming: vi.fn(),
      sensitiveMode: true,
      suppressedSources: ["note"],
      toggleSensitiveMode,
      toggleSuppressedSource,
    });

    render(
      <MemoryRouter initialEntries={["/chat?prompt=Plan%20privately"]}>
        <ChatPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(setInputValue).toHaveBeenCalledWith("Plan privately");
    });
    expect(screen.getByRole("button", { name: "Hidden: Notes" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Saved memories" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Sensitive mode" }));
    await user.click(screen.getByRole("button", { name: "Hidden: Notes" }));
    await user.click(screen.getByRole("button", { name: "Saved memories" }));

    expect(toggleSensitiveMode).toHaveBeenCalledOnce();
    expect(toggleSuppressedSource).toHaveBeenCalledWith("note");
    expect(toggleSuppressedSource).toHaveBeenCalledWith("saved_memory");
  });
});

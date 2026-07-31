import { describe, it, expect, vi } from "vitest";
import { renderWithProviders, screen, userEvent } from "../../test-utils";
import { ChatInput } from "@/components/chat/chat-input";

describe("ChatInput", () => {
  const defaultProps = {
    onSend: vi.fn(),
    onStop: vi.fn(),
    isStreaming: false,
    value: "",
    onChange: vi.fn(),
  };

  function renderInput(overrides: Partial<typeof defaultProps> = {}) {
    const props = { ...defaultProps, ...overrides };
    // Reset mocks from defaultProps for each render call
    return {
      ...renderWithProviders(<ChatInput {...props} />),
      props,
    };
  }

  it("renders a textarea", () => {
    renderInput();
    expect(screen.getByPlaceholderText("Ask anything...")).toBeInTheDocument();
  });

  it("renders a textarea with the provided value", () => {
    renderInput({ value: "Hello there" });
    const textarea = screen.getByPlaceholderText("Ask anything...");
    expect(textarea).toHaveValue("Hello there");
  });

  it("calls onChange when text is typed", async () => {
    const onChange = vi.fn();
    renderInput({ onChange });

    const textarea = screen.getByPlaceholderText("Ask anything...");
    const user = userEvent.setup();
    await user.type(textarea, "a");

    expect(onChange).toHaveBeenCalled();
  });

  it("submits on Enter key (not Shift+Enter)", async () => {
    const onSend = vi.fn();
    renderInput({ value: "Hello", onSend });

    const textarea = screen.getByPlaceholderText("Ask anything...");
    const user = userEvent.setup();

    // Focus the textarea and press Enter
    await user.click(textarea);
    await user.keyboard("{Enter}");

    expect(onSend).toHaveBeenCalledWith("Hello");
  });

  it("does not submit on Shift+Enter (allows newline)", async () => {
    const onSend = vi.fn();
    renderInput({ value: "Hello", onSend });

    const textarea = screen.getByPlaceholderText("Ask anything...");
    const user = userEvent.setup();

    await user.click(textarea);
    await user.keyboard("{Shift>}{Enter}{/Shift}");

    expect(onSend).not.toHaveBeenCalled();
  });

  it("does not submit when the value is empty", async () => {
    const onSend = vi.fn();
    renderInput({ value: "", onSend });

    const textarea = screen.getByPlaceholderText("Ask anything...");
    const user = userEvent.setup();

    await user.click(textarea);
    await user.keyboard("{Enter}");

    expect(onSend).not.toHaveBeenCalled();
  });

  it("does not submit when the value is only whitespace", async () => {
    const onSend = vi.fn();
    renderInput({ value: "   ", onSend });

    const textarea = screen.getByPlaceholderText("Ask anything...");
    const user = userEvent.setup();

    await user.click(textarea);
    await user.keyboard("{Enter}");

    expect(onSend).not.toHaveBeenCalled();
  });

  it("clears the input via onChange after submitting", async () => {
    const onChange = vi.fn();
    const onSend = vi.fn();
    renderInput({ value: "Hello", onChange, onSend });

    const textarea = screen.getByPlaceholderText("Ask anything...");
    const user = userEvent.setup();

    await user.click(textarea);
    await user.keyboard("{Enter}");

    expect(onSend).toHaveBeenCalledWith("Hello");
    expect(onChange).toHaveBeenCalledWith("");
  });

  it("disables the textarea when isStreaming is true", () => {
    renderInput({ isStreaming: true });
    const textarea = screen.getByPlaceholderText("Ask anything...");
    expect(textarea).toBeDisabled();
  });

  it("shows stop button when streaming", () => {
    renderInput({ isStreaming: true });
    expect(screen.getByRole("button", { name: /stop generation/i })).toBeInTheDocument();
  });

  it("shows send button when not streaming", () => {
    renderInput({ isStreaming: false, value: "Hi" });
    expect(screen.getByRole("button", { name: /send message/i })).toBeInTheDocument();
  });

  it("calls onStop when the stop button is clicked", async () => {
    const onStop = vi.fn();
    renderInput({ isStreaming: true, onStop });

    const stopBtn = screen.getByRole("button", { name: /stop generation/i });
    const user = userEvent.setup();
    await user.click(stopBtn);

    expect(onStop).toHaveBeenCalledOnce();
  });

  it("disables the send button when value is empty", () => {
    renderInput({ value: "" });
    const sendBtn = screen.getByRole("button", { name: /send message/i });
    expect(sendBtn).toBeDisabled();
  });

  it("enables the send button when there is text and not streaming", () => {
    renderInput({ value: "Some text" });
    const sendBtn = screen.getByRole("button", { name: /send message/i });
    expect(sendBtn).not.toBeDisabled();
  });

  it("submits via the send button click", async () => {
    const onSend = vi.fn();
    const onChange = vi.fn();
    renderInput({ value: "Click send", onSend, onChange });

    const sendBtn = screen.getByRole("button", { name: /send message/i });
    const user = userEvent.setup();
    await user.click(sendBtn);

    expect(onSend).toHaveBeenCalledWith("Click send");
    expect(onChange).toHaveBeenCalledWith("");
  });
});

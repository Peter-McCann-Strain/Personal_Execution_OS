import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent } from "@testing-library/react";
import { renderWithProviders, screen, waitFor } from "../../test-utils";
import { QuickCaptureModal } from "@/components/diary/quick-capture-modal";

const mocks = vi.hoisted(() => ({
  sendChatMessage: vi.fn(),
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: {
    error: mocks.toastError,
    success: mocks.toastSuccess,
  },
}));

vi.mock("@/api/chat", () => ({
  sendChatMessage: mocks.sendChatMessage,
}));

describe("QuickCaptureModal", () => {
  beforeEach(() => {
    mocks.sendChatMessage.mockReset();
    mocks.toastError.mockReset();
    mocks.toastSuccess.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("opens from the global shortcut and submits a capture", async () => {
    mocks.sendChatMessage.mockResolvedValue({
      content: "Captured",
      agent: "diary",
      metadata: {
        mood_score: 7.2,
        energy_rating: 6.1,
        para_category: "resource",
        tags: ["focus", "work"],
      },
    });

    renderWithProviders(<QuickCaptureModal />);

    fireEvent.keyDown(window, { key: "n", ctrlKey: true });

    expect(await screen.findByRole("dialog", { name: "What's on your mind?" })).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Type anything..."), {
      target: { value: "Quick note" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Capture" }));

    await waitFor(() => {
      expect(mocks.sendChatMessage).toHaveBeenCalledWith("Quick note", "api");
    });

    expect(mocks.toastSuccess).toHaveBeenCalledWith(
      "Entry captured!",
      expect.objectContaining({
        description: expect.stringContaining("Mood: 7.2"),
      }),
    );
    await waitFor(() => {
      expect(
        screen.queryByRole("dialog", { name: "What's on your mind?" }),
      ).not.toBeInTheDocument();
    });
  });

  it("ignores blank submits, handles keyboard submission, and surfaces failures", async () => {
    mocks.sendChatMessage.mockRejectedValueOnce(new Error("boom"));

    renderWithProviders(<QuickCaptureModal />);

    fireEvent.keyDown(window, { key: "n", ctrlKey: true });

    expect(await screen.findByRole("dialog", { name: "What's on your mind?" })).toBeInTheDocument();

    const textarea = screen.getByPlaceholderText("Type anything...");

    fireEvent.change(textarea, {
      target: { value: "   " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Capture" }));
    expect(mocks.sendChatMessage).not.toHaveBeenCalled();

    fireEvent.change(textarea, {
      target: { value: "Needs attention" },
    });
    fireEvent.keyDown(textarea, { key: "Enter", ctrlKey: true });

    await waitFor(() => {
      expect(mocks.sendChatMessage).toHaveBeenCalledWith("Needs attention", "api");
    });
    await waitFor(() => {
      expect(mocks.toastError).toHaveBeenCalledWith("boom");
    });

    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => {
      expect(
        screen.queryByRole("dialog", { name: "What's on your mind?" }),
      ).not.toBeInTheDocument();
    });
  });

  it("supports external control, auto-resizes, and uses fallback success metadata", async () => {
    const onExternalOpenChange = vi.fn();

    mocks.sendChatMessage.mockResolvedValue({
      content: "Captured",
      agent: "diary",
      metadata: null,
    });

    renderWithProviders(
      <QuickCaptureModal externalOpen onExternalOpenChange={onExternalOpenChange} />,
    );

    const textarea = screen.getByPlaceholderText("Type anything...");
    Object.defineProperty(textarea, "scrollHeight", {
      configurable: true,
      value: 500,
    });

    fireEvent.change(textarea, { target: { value: "  Keyboard capture  " } });
    expect(textarea).toHaveStyle({ height: "288px" });

    fireEvent.keyDown(textarea, { key: "Enter", ctrlKey: true });

    await waitFor(() => {
      expect(mocks.sendChatMessage).toHaveBeenCalledWith("Keyboard capture", "api");
    });
    expect(mocks.toastSuccess).toHaveBeenCalledWith(
      "Entry captured!",
      expect.objectContaining({
        description: "Processing complete.",
      }),
    );
    expect(onExternalOpenChange).toHaveBeenCalledWith(false);
  });
});

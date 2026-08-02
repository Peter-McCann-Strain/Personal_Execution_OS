import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import { renderWithProviders, waitFor } from "../../test-utils";
import { RuntimeStreamBridge } from "@/components/layout/runtime-stream-bridge";
import { useAppStore } from "@/stores/app";

function resetAppStore() {
  useAppStore.setState({
    apiKey: "",
    runtimeStreamStatus: "idle",
  });
}

describe("RuntimeStreamBridge", () => {
  beforeEach(() => {
    resetAppStore();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    resetAppStore();
  });

  it("moves to live status when the runtime stream connects", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            'event: runtime_snapshot\ndata: {"generated_at":"2026-04-14T00:20:00Z","workflow_total":1}\n\n',
          ),
        );
        controller.close();
      },
    });

    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(stream, {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      }),
    );

    useAppStore.setState({
      apiKey: "test-api-key",
      runtimeStreamStatus: "idle",
    });

    const view = renderWithProviders(<RuntimeStreamBridge />);

    await waitFor(() => {
      expect(useAppStore.getState().runtimeStreamStatus).toBe("live");
    });
    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ credentials: "same-origin" }),
    );

    view.unmount();
  });

  it("does not open a protected stream without the required development key", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    const view = renderWithProviders(<RuntimeStreamBridge />);
    await Promise.resolve();

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(useAppStore.getState().runtimeStreamStatus).toBe("idle");
    view.unmount();
  });

  it.each([
    [new Response("unavailable", { status: 503 }), "a non-successful runtime response"],
    [new Response(null, { status: 200 }), "a response without a readable body"],
  ])("moves to error state for %s", async (response) => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response);
    useAppStore.setState({ apiKey: "test-api-key" });

    const view = renderWithProviders(<RuntimeStreamBridge />);

    await waitFor(() => {
      expect(useAppStore.getState().runtimeStreamStatus).toBe("error");
    });
    view.unmount();
    expect(useAppStore.getState().runtimeStreamStatus).toBe("idle");
  });

  it("surfaces runtime error events after a valid stream handshake", async () => {
    const stream = streamFromChunks([
      'event: runtime_error\ndata: {"message":"worker unavailable"}\n\n',
    ]);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(stream, {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      }),
    );
    useAppStore.setState({ apiKey: "test-api-key" });

    const view = renderWithProviders(<RuntimeStreamBridge />);

    await waitFor(() => {
      expect(useAppStore.getState().runtimeStreamStatus).toBe("error");
    });
    view.unmount();
  });

  it("invalidates live data once per distinct snapshot or update", async () => {
    const invalidate = vi
      .spyOn(QueryClient.prototype, "invalidateQueries")
      .mockResolvedValue(undefined);
    const first = '{"workflow_total":1}';
    const second = '{"workflow_total":2}';
    const stream = streamFromChunks([
      `: heartbeat\n\nevent: runtime_snapshot\ndata: ${first}\n\n`,
      `event: runtime_snapshot\ndata: ${first}\n\n`,
      `event: runtime_update\ndata: ${second}\n\n`,
    ]);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(stream, { status: 200 }));
    useAppStore.setState({ apiKey: "test-api-key" });

    const view = renderWithProviders(<RuntimeStreamBridge />);

    await waitFor(() => {
      expect(invalidate).toHaveBeenCalledTimes(20);
    });
    expect(useAppStore.getState().runtimeStreamStatus).toBe("live");
    view.unmount();
  });

  it("buffers an incomplete event without invalidating live queries", async () => {
    const invalidate = vi
      .spyOn(QueryClient.prototype, "invalidateQueries")
      .mockResolvedValue(undefined);
    const stream = streamFromChunks(['event: runtime_snapshot\ndata: {"workflow_total":1}']);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(stream, { status: 200 }));
    useAppStore.setState({ apiKey: "test-api-key" });

    const view = renderWithProviders(<RuntimeStreamBridge />);

    await waitFor(() => {
      expect(useAppStore.getState().runtimeStreamStatus).toBe("live");
    });
    expect(invalidate).not.toHaveBeenCalled();
    view.unmount();
  });

  it("uses and cancels the browser idle callback when available", async () => {
    const cancelIdleCallback = vi.fn();
    const requestIdleCallback = vi.fn((callback: () => void) => {
      queueMicrotask(callback);
      return 17;
    });
    Object.defineProperty(window, "requestIdleCallback", {
      value: requestIdleCallback,
      configurable: true,
    });
    Object.defineProperty(window, "cancelIdleCallback", {
      value: cancelIdleCallback,
      configurable: true,
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(streamFromChunks([]), { status: 200 }),
    );
    useAppStore.setState({ apiKey: "test-api-key" });

    const view = renderWithProviders(<RuntimeStreamBridge />);
    await waitFor(() => expect(requestIdleCallback).toHaveBeenCalledOnce());
    view.unmount();

    expect(cancelIdleCallback).toHaveBeenCalledWith(17);
    Reflect.deleteProperty(window, "requestIdleCallback");
    Reflect.deleteProperty(window, "cancelIdleCallback");
  });

  it("waits for the window load event before starting the long-lived request", async () => {
    vi.spyOn(document, "readyState", "get").mockReturnValue("loading");
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(streamFromChunks([]), { status: 200 }));
    useAppStore.setState({ apiKey: "test-api-key" });

    const view = renderWithProviders(<RuntimeStreamBridge />);
    expect(fetchSpy).not.toHaveBeenCalled();

    window.dispatchEvent(new Event("load"));
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledOnce());
    view.unmount();
  });

  it("removes a pending load listener and ignores stale callbacks on unmount", () => {
    vi.spyOn(document, "readyState", "get").mockReturnValue("loading");
    let capturedLoadHandler: EventListener | null = null;
    const addEventListener = vi
      .spyOn(window, "addEventListener")
      .mockImplementation((type, listener) => {
        if (type === "load") capturedLoadHandler = listener as EventListener;
      });
    const removeEventListener = vi.spyOn(window, "removeEventListener");
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    useAppStore.setState({ apiKey: "test-api-key" });

    const view = renderWithProviders(<RuntimeStreamBridge />);
    expect(addEventListener).toHaveBeenCalledWith("load", expect.any(Function), { once: true });
    view.unmount();
    expect(removeEventListener).toHaveBeenCalledWith("load", capturedLoadHandler);

    capturedLoadHandler?.(new Event("load"));
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("stops quietly when an in-flight connection is aborted during unmount", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((_input, init) => {
      return new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () =>
          reject(new DOMException("aborted", "AbortError")),
        );
      });
    });
    useAppStore.setState({ apiKey: "test-api-key" });

    const view = renderWithProviders(<RuntimeStreamBridge />);
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledOnce());
    view.unmount();

    await Promise.resolve();
    expect(useAppStore.getState().runtimeStreamStatus).toBe("idle");
  });
});

function streamFromChunks(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
}

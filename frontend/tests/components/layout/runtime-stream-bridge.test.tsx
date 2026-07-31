import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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
});

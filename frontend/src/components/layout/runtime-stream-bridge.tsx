import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { getApiRequestHeaders } from "@/api/client";
import { API_PATHS } from "@/api/generated/paths";
import { isLegacyDevAuthEnabled } from "@/lib/auth-mode";
import { useAppStore } from "@/stores/app";

type RuntimeStreamEvent =
  | { event: "runtime_open"; data: Record<string, unknown> }
  | {
      event: "runtime_snapshot" | "runtime_update";
      data: Record<string, unknown>;
    }
  | { event: "runtime_heartbeat"; data: Record<string, unknown> }
  | { event: "runtime_error"; data: { message?: string } };

function parseSSEChunk(chunk: string): RuntimeStreamEvent[] {
  const events: RuntimeStreamEvent[] = [];
  const rawEvents = chunk.split("\n\n");

  for (const rawEvent of rawEvents) {
    const trimmed = rawEvent.trim();
    if (!trimmed) continue;

    let eventName = "message";
    const dataLines: string[] = [];
    for (const line of trimmed.split("\n")) {
      if (line.startsWith(":")) continue;
      if (line.startsWith("event:")) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trimStart());
      }
    }

    if (dataLines.length === 0) continue;
    const dataText = dataLines.join("\n");
    const parsed = JSON.parse(dataText) as Record<string, unknown>;
    events.push({
      event: eventName as RuntimeStreamEvent["event"],
      data: parsed,
    } as RuntimeStreamEvent);
  }

  return events;
}

function RuntimeStreamBridge() {
  const queryClient = useQueryClient();
  const apiKey = useAppStore((state) => state.apiKey);
  const setRuntimeStreamStatus = useAppStore((state) => state.setRuntimeStreamStatus);
  const lastSignatureRef = useRef<string | null>(null);

  useEffect(() => {
    if (isLegacyDevAuthEnabled && !apiKey) {
      setRuntimeStreamStatus("idle");
      return;
    }

    let cancelled = false;
    let reconnectTimer: number | null = null;
    let startTimer: number | null = null;
    let idleHandle: number | null = null;
    let removeLoadListener: (() => void) | null = null;
    const controller = new AbortController();

    function invalidateLiveQueries(): void {
      queryClient.invalidateQueries({ queryKey: ["pulse", "agent-runs"] });
      queryClient.invalidateQueries({ queryKey: ["agent-run"] });
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
      queryClient.invalidateQueries({ queryKey: ["pulse", "notifications"] });
      queryClient.invalidateQueries({ queryKey: ["pulse", "scheduled-actions"] });
      queryClient.invalidateQueries({ queryKey: ["pulse", "scheduled-action-runs"] });
      queryClient.invalidateQueries({ queryKey: ["pulse", "web-push-config"] });
      queryClient.invalidateQueries({ queryKey: ["pulse", "web-push-subscriptions"] });
      queryClient.invalidateQueries({ queryKey: ["notifications", "push"] });
      queryClient.invalidateQueries({ queryKey: ["native-bridge"] });
    }

    async function connect(): Promise<void> {
      setRuntimeStreamStatus("connecting");

      try {
        const authHeaders = await getApiRequestHeaders(false, { apiKey });

        const response = await fetch(API_PATHS.apiRuntimeStream, {
          method: "GET",
          credentials: "same-origin",
          headers: authHeaders,
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(`Runtime stream failed (${response.status})`);
        }

        const reader = response.body?.getReader();
        if (!reader) {
          throw new Error("Runtime stream did not provide a readable body.");
        }

        setRuntimeStreamStatus("live");
        let buffer = "";
        const decoder = new TextDecoder();

        while (!cancelled) {
          const { done, value } = await reader.read();
          if (done) {
            break;
          }
          buffer += decoder.decode(value, { stream: true });
          const eventBoundary = buffer.lastIndexOf("\n\n");
          if (eventBoundary === -1) {
            continue;
          }

          const complete = buffer.slice(0, eventBoundary + 2);
          buffer = buffer.slice(eventBoundary + 2);
          for (const event of parseSSEChunk(complete)) {
            if (event.event === "runtime_snapshot" || event.event === "runtime_update") {
              const signature = JSON.stringify(event.data);
              if (signature === lastSignatureRef.current) {
                continue;
              }
              lastSignatureRef.current = signature;
              invalidateLiveQueries();
              continue;
            }

            if (event.event === "runtime_error") {
              setRuntimeStreamStatus("error");
            }
          }
        }
      } catch {
        if (controller.signal.aborted || cancelled) {
          return;
        }
        setRuntimeStreamStatus("error");
      }

      if (cancelled) {
        return;
      }
      reconnectTimer = window.setTimeout(() => {
        void connect();
      }, 2_000);
    }

    // Defer opening the streaming fetch until after the page has finished
    // loading. Without this guard the long-lived SSE response keeps the
    // browser tab in a "loading" state, which causes Playwright (and some
    // browser navigation hooks) to hang waiting for a settled network even
    // when `waitUntil: "domcontentloaded"` was requested.
    function startConnect(): void {
      if (cancelled) {
        return;
      }
      // Use requestIdleCallback when available so the connection waits for an
      // idle frame; fall back to a small timeout. Either way the fetch is
      // initiated AFTER the current task and AFTER the load event has fired.
      type IdleCallback = (cb: () => void, opts?: { timeout: number }) => number;
      const ric = (window as unknown as { requestIdleCallback?: IdleCallback }).requestIdleCallback;
      if (typeof ric === "function") {
        idleHandle = ric(
          () => {
            if (!cancelled) void connect();
          },
          { timeout: 1_000 },
        );
      } else {
        startTimer = window.setTimeout(() => {
          if (!cancelled) void connect();
        }, 0);
      }
    }

    if (document.readyState === "complete") {
      startConnect();
    } else {
      const handleLoad = () => {
        removeLoadListener = null;
        startConnect();
      };
      window.addEventListener("load", handleLoad, { once: true });
      removeLoadListener = () => window.removeEventListener("load", handleLoad);
    }

    return () => {
      cancelled = true;
      controller.abort();
      setRuntimeStreamStatus("idle");
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
      }
      if (startTimer !== null) {
        window.clearTimeout(startTimer);
      }
      if (idleHandle !== null) {
        type CancelIdleCallback = (handle: number) => void;
        const cic = (window as unknown as { cancelIdleCallback?: CancelIdleCallback })
          .cancelIdleCallback;
        if (typeof cic === "function") {
          cic(idleHandle);
        }
      }
      if (removeLoadListener) {
        removeLoadListener();
      }
    };
  }, [apiKey, queryClient, setRuntimeStreamStatus]);

  return null;
}

export { RuntimeStreamBridge };

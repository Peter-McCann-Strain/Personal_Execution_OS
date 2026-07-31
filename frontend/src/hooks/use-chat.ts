import { useCallback, useRef, useState } from "react";
import { toast } from "sonner";
import { getApiRequestHeaders } from "@/api/client";
import { API_PATHS } from "@/api/generated/paths";
import { useChatStore } from "@/stores/chat";
import { useAppStore } from "@/stores/app";
import type { ChatMessage } from "@/types";

type MemorySourceKey = "episode" | "note" | "saved_memory" | "connector_document";

function generateId(): string {
  return crypto.randomUUID();
}

type StreamEvent =
  | { event: "message_start"; data: { request_id?: string; source?: string } }
  | { event: "token"; data: { content?: string } }
  | { event: "agent"; data: { agent?: string } }
  | { event: "tool_status"; data: { tool_calls?: unknown[]; tool_count?: number; errors?: number } }
  | {
      event: "message_end";
      data: { content?: string; agent?: string; metadata?: Record<string, unknown> };
    }
  | { event: "error"; data: { error?: string; error_type?: string; request_id?: string } };

// SSE separators per the spec: \r\n\r\n, \n\n, or \r\r between events; lines
// inside an event are split on any of \r\n, \n, or \r. We normalise CRLF/CR to
// LF so the rest of the parser can use a single boundary string.
function normaliseLineEndings(chunk: string): string {
  return chunk.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
}

export function parseSSEChunk(chunk: string): StreamEvent[] {
  const events: StreamEvent[] = [];
  const normalised = normaliseLineEndings(chunk);
  const rawEvents = normalised.split("\n\n");

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
    if (dataText === "[DONE]") continue;

    let parsed: StreamEvent["data"];
    try {
      parsed = JSON.parse(dataText) as StreamEvent["data"];
    } catch {
      // Skip malformed payloads instead of aborting the whole chunk —
      // a single bad event must not lose every following token.
      continue;
    }

    events.push({
      event: eventName as StreamEvent["event"],
      data: parsed,
    } as StreamEvent);
  }

  return events;
}

export function useChat() {
  const [inputValue, setInputValue] = useState("");
  const [sensitiveMode, setSensitiveMode] = useState(false);
  const [suppressedSources, setSuppressedSources] = useState<MemorySourceKey[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  const {
    messages,
    isStreaming,
    addMessage,
    updateLastMessage,
    patchLastMessage,
    setStreaming,
    setActiveAgent,
    clearMessages,
  } = useChatStore();

  const apiKey = useAppStore((s) => s.apiKey);

  const stopStreaming = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
  }, []);

  const parseHttpError = useCallback(async (response: Response): Promise<string> => {
    const body = await response.text().catch(() => "");
    if (!body) {
      return `Chat failed (${response.status})`;
    }

    try {
      const parsed = JSON.parse(body) as { message?: string; detail?: string };
      const detail = parsed.message ?? parsed.detail;
      if (detail) {
        return `Chat failed (${response.status}): ${detail}`;
      }
    } catch {
      // Fall back to the raw response body when it is not JSON.
    }

    return `Chat failed (${response.status}): ${body}`;
  }, []);

  const toggleSensitiveMode = useCallback(() => {
    setSensitiveMode((current) => !current);
  }, []);

  const toggleSuppressedSource = useCallback((source: MemorySourceKey) => {
    setSuppressedSources((current) =>
      current.includes(source) ? current.filter((value) => value !== source) : [...current, source],
    );
  }, []);

  const sendMessage = useCallback(
    async (content: string) => {
      if (!content.trim() || isStreaming) return;

      // Add user message to store
      const userMessage: ChatMessage = {
        id: generateId(),
        role: "user",
        content: content.trim(),
        timestamp: new Date().toISOString(),
      };
      addMessage(userMessage);

      // Add placeholder assistant message that we will stream into
      const assistantMessage: ChatMessage = {
        id: generateId(),
        role: "assistant",
        content: "",
        timestamp: new Date().toISOString(),
        isStreaming: true,
      };
      addMessage(assistantMessage);
      setStreaming(true);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const headers = await getApiRequestHeaders(true, { apiKey }, true);
        if (controller.signal.aborted) {
          return;
        }

        const response = await fetch(API_PATHS.apiChatStream, {
          method: "POST",
          credentials: "same-origin",
          headers,
          body: JSON.stringify({
            content: content.trim(),
            source: "api",
            sensitive_mode: sensitiveMode,
            suppressed_sources: suppressedSources,
          }),
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(await parseHttpError(response));
        }

        const reader = response.body?.getReader();
        const decoder = new TextDecoder();
        let accumulated = "";
        let buffer = "";

        if (reader) {
          // Flush a final empty decode so any trailing bytes from the last
          // chunk are surfaced before we exit the loop.
          let streamFinished = false;
          while (!streamFinished) {
            const { done, value } = await reader.read();
            if (done) {
              buffer += decoder.decode();
              streamFinished = true;
            } else {
              buffer += decoder.decode(value, { stream: true });
            }

            // Normalise CRLF and CR to LF so the boundary check is reliable
            // even if a proxy rewrites the line endings.
            buffer = buffer.replace(/\r\n/g, "\n").replace(/\r/g, "\n");

            const eventBoundary = buffer.lastIndexOf("\n\n");
            if (eventBoundary === -1) continue;

            const complete = buffer.slice(0, eventBoundary + 2);
            buffer = buffer.slice(eventBoundary + 2);

            for (const event of parseSSEChunk(complete)) {
              if (event.event === "token" && event.data.content) {
                accumulated += event.data.content;
                updateLastMessage(accumulated);
                continue;
              }

              if (event.event === "agent" && event.data.agent) {
                setActiveAgent(event.data.agent);
                patchLastMessage({ agent: event.data.agent as ChatMessage["agent"] });
                continue;
              }

              if (event.event === "tool_status") {
                patchLastMessage({
                  metadata: {
                    tool_calls: event.data.tool_calls ?? [],
                    tool_count: event.data.tool_count,
                    errors: event.data.errors,
                  },
                });
                continue;
              }

              if (event.event === "message_end") {
                if (!accumulated && event.data.content) {
                  accumulated = event.data.content;
                  updateLastMessage(accumulated);
                }
                patchLastMessage({
                  agent: event.data.agent as ChatMessage["agent"],
                  metadata: event.data.metadata,
                });
                if (event.data.agent) {
                  setActiveAgent(event.data.agent);
                }
                continue;
              }

              if (event.event === "error") {
                throw new Error(event.data.error || "Unknown streaming error");
              }
            }
          }
        }

        if (!accumulated) {
          throw new Error("Assistant returned an empty response.");
        }
      } catch (err) {
        if ((err as Error).name === "AbortError") {
          // User cancelled - mark the partial message as done
          // Content stays as whatever was accumulated
        } else {
          const errorMessage = err instanceof Error ? err.message : "Failed to send message";

          toast.error("Message failed", {
            description: errorMessage,
            duration: 8000,
          });

          updateLastMessage(errorMessage);
          patchLastMessage({
            metadata: {
              error: true,
              error_message: errorMessage,
            },
          });
        }
      } finally {
        setStreaming(false);
        setActiveAgent(null);
        abortRef.current = null;

        // Clear the isStreaming flag on the last message
        useChatStore.getState().finalizeLastMessage();
      }
    },
    [
      isStreaming,
      addMessage,
      updateLastMessage,
      patchLastMessage,
      setStreaming,
      setActiveAgent,
      apiKey,
      parseHttpError,
      sensitiveMode,
      suppressedSources,
    ],
  );

  return {
    messages,
    isStreaming,
    inputValue,
    setInputValue,
    sendMessage,
    stopStreaming,
    clearMessages,
    sensitiveMode,
    suppressedSources,
    toggleSensitiveMode,
    toggleSuppressedSource,
  };
}

/**
 * Component test for the chat SSE consumer.
 *
 * Renders the real `ChatPage` against the real Zustand stores and mocks
 * `fetch` with an SSE `ReadableStream`. Asserts that `event: token` payloads
 * are appended to the assistant bubble's content as they arrive.
 *
 * Regression target (P1.2, 2026-04-18): the assistant bubble appeared but
 * stayed empty when the backend returned tokens correctly via SSE.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { screen, waitFor, type RenderOptions } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChatPage } from "@/pages/chat";
import { useChatStore } from "@/stores/chat";
import { useAppStore } from "@/stores/app";
import { parseSSEChunk } from "@/hooks/use-chat";

function renderWithProviders(ui: React.ReactElement, options?: RenderOptions) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const Wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
  return render(ui, { wrapper: Wrapper, ...options });
}

function createSSEStream(chunks: string[]): ReadableStream<Uint8Array> {
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

function streamResponse(stream: ReadableStream<Uint8Array>): Response {
  return {
    ok: true,
    status: 200,
    body: stream,
    headers: new Headers({ "content-type": "text/event-stream" }),
    text: () => Promise.resolve(""),
    redirected: false,
    statusText: "OK",
    type: "basic" as ResponseType,
    url: "",
    clone: () => ({}) as Response,
    arrayBuffer: () => Promise.resolve(new ArrayBuffer(0)),
    blob: () => Promise.resolve(new Blob()),
    formData: () => Promise.resolve(new FormData()),
    json: () => Promise.resolve({}),
    bytes: () => Promise.resolve(new Uint8Array()),
  } as Response;
}

describe("useChat SSE rendering (component-level)", () => {
  const originalScrollIntoView = HTMLElement.prototype.scrollIntoView;

  beforeEach(() => {
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: vi.fn(),
    });
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
      cb(0);
      return 0;
    });
    useChatStore.setState({ messages: [], isStreaming: false, activeAgent: null });
    useAppStore.setState({ apiKey: "test-key" });
  });

  afterEach(() => {
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: originalScrollIntoView,
    });
    vi.unstubAllGlobals();
  });

  it("appends streamed token content into the assistant bubble", async () => {
    const user = userEvent.setup();
    const stream = createSSEStream([
      'event: message_start\ndata: {"request_id":"req-1","source":"api"}\n\n' +
        'event: agent\ndata: {"agent":"diary"}\n\n' +
        'event: token\ndata: {"content":"Still "}\n\n' +
        'event: token\ndata: {"content":"here."}\n\n' +
        'event: message_end\ndata: {"content":"Still here.","agent":"diary","metadata":{"request_id":"req-1"}}\n\n',
    ]);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(streamResponse(stream)));

    renderWithProviders(<ChatPage />);

    await user.type(screen.getByPlaceholderText("Ask anything..."), "Are you there?");
    await user.click(screen.getByRole("button", { name: /send message/i }));

    await waitFor(() => {
      expect(screen.getByText(/Still here\./)).toBeInTheDocument();
    });
  });

  it("rejoins token bytes that arrive split across two reads", async () => {
    const user = userEvent.setup();
    const stream = createSSEStream([
      'event: token\ndata: {"content":"Hel',
      'lo"}\n\nevent: message_end\ndata: {"content":"Hello","agent":"diary","metadata":{}}\n\n',
    ]);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(streamResponse(stream)));

    renderWithProviders(<ChatPage />);

    await user.type(screen.getByPlaceholderText("Ask anything..."), "Hi");
    await user.click(screen.getByRole("button", { name: /send message/i }));

    await waitFor(() => {
      expect(screen.getByText("Hello")).toBeInTheDocument();
    });
  });

  it("normalises CRLF separators that some proxies emit", async () => {
    const user = userEvent.setup();
    const stream = createSSEStream([
      'event: token\r\ndata: {"content":"crlf "}\r\n\r\n' +
        'event: token\r\ndata: {"content":"works"}\r\n\r\n' +
        'event: message_end\r\ndata: {"content":"crlf works","agent":"diary","metadata":{}}\r\n\r\n',
    ]);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(streamResponse(stream)));

    renderWithProviders(<ChatPage />);

    await user.type(screen.getByPlaceholderText("Ask anything..."), "Hi");
    await user.click(screen.getByRole("button", { name: /send message/i }));

    await waitFor(() => {
      expect(screen.getByText(/crlf works/)).toBeInTheDocument();
    });
  });
});

describe("parseSSEChunk", () => {
  it("parses well-formed events with LF separators", () => {
    const chunk =
      'event: token\ndata: {"content":"a"}\n\n' + 'event: token\ndata: {"content":"b"}\n\n';
    const events = parseSSEChunk(chunk);
    expect(events).toHaveLength(2);
    expect(events[0]).toMatchObject({ event: "token", data: { content: "a" } });
    expect(events[1]).toMatchObject({ event: "token", data: { content: "b" } });
  });

  it("normalises CRLF separators", () => {
    const chunk =
      'event: token\r\ndata: {"content":"a"}\r\n\r\n' +
      'event: token\r\ndata: {"content":"b"}\r\n\r\n';
    const events = parseSSEChunk(chunk);
    expect(events).toHaveLength(2);
  });

  it("skips malformed JSON without losing later events", () => {
    const chunk = "event: token\ndata: not-json\n\n" + 'event: token\ndata: {"content":"good"}\n\n';
    const events = parseSSEChunk(chunk);
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({ event: "token", data: { content: "good" } });
  });
});

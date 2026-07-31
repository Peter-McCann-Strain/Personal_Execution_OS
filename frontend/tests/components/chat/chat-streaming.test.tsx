/**
 * Integration tests for the chat streaming UI.
 *
 * These exercise the full ChatPage with real Zustand stores so a regression
 * in the SSE consumer (such as no tokens rendering despite a 200 from the
 * backend) is caught at the component level — not just the hook level.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent, waitFor } from "../../test-utils";
import { ChatPage } from "@/pages/chat";
import { useChatStore } from "@/stores/chat";
import { useAppStore } from "@/stores/app";

/**
 * Build a ReadableStream that emits one SSE chunk per call, mirroring how
 * uvicorn flushes events back to the browser.
 */
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

function streamResponse(stream: ReadableStream<Uint8Array>, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
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

describe("ChatPage SSE streaming integration", () => {
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
    // Reset the persisted Zustand stores between tests.
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

  it("renders streamed tokens into the assistant bubble (single combined chunk)", async () => {
    const user = userEvent.setup();
    // Production scenario: Anthropic returns the whole reply, then uvicorn
    // flushes every SSE event in a single TCP packet. The reader sees one
    // chunk containing every event back-to-back.
    const stream = createSSEStream([
      'event: message_start\ndata: {"request_id":"req-1","source":"api"}\n\n' +
        'event: agent\ndata: {"agent":"diary"}\n\n' +
        'event: token\ndata: {"content":"Still "}\n\n' +
        'event: token\ndata: {"content":"here."}\n\n' +
        'event: message_end\ndata: {"content":"Still here.","agent":"diary","metadata":{"request_id":"req-1"}}\n\n',
    ]);
    const fetchMock = vi.fn().mockResolvedValue(streamResponse(stream));
    vi.stubGlobal("fetch", fetchMock);

    renderWithProviders(<ChatPage />);

    const textarea = screen.getByPlaceholderText("Ask anything...");
    await user.type(textarea, "Hi");
    await user.click(screen.getByRole("button", { name: /send message/i }));

    expect(fetchMock).toHaveBeenCalledOnce();

    await waitFor(() => {
      expect(screen.getByText(/Still here\./)).toBeInTheDocument();
    });
  });

  it("renders tokens that arrive split across multiple network chunks", async () => {
    const user = userEvent.setup();
    // The reader can deliver an event split across two reads — make sure
    // the buffer rejoins the bytes before parsing.
    const stream = createSSEStream([
      'event: token\ndata: {"content":"Hello',
      ' world"}\n\n' +
        'event: message_end\ndata: {"content":"Hello world","agent":"diary","metadata":{}}\n\n',
    ]);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(streamResponse(stream)));

    renderWithProviders(<ChatPage />);

    await user.type(screen.getByPlaceholderText("Ask anything..."), "Hi");
    await user.click(screen.getByRole("button", { name: /send message/i }));

    await waitFor(() => {
      expect(screen.getByText(/Hello world/)).toBeInTheDocument();
    });
  });

  it("falls back to message_end content when no token events are emitted", async () => {
    const user = userEvent.setup();
    // Some agents skip tokenisation and only send the final message_end —
    // the bubble must still show the content rather than 'returned an empty
    // response.'
    const stream = createSSEStream([
      'event: message_end\ndata: {"content":"Direct reply","agent":"diary","metadata":{}}\n\n',
    ]);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(streamResponse(stream)));

    renderWithProviders(<ChatPage />);

    await user.type(screen.getByPlaceholderText("Ask anything..."), "Hi");
    await user.click(screen.getByRole("button", { name: /send message/i }));

    await waitFor(() => {
      expect(screen.getByText("Direct reply")).toBeInTheDocument();
    });
  });

  it("renders tokens when the proxy rewrites separators to CRLF", async () => {
    const user = userEvent.setup();
    // Defensive: some reverse proxies (and HTTP/2 implementations) rewrite
    // SSE separators to \r\n\r\n. The parser must treat them identically.
    const stream = createSSEStream([
      'event: token\r\ndata: {"content":"Robust "}\r\n\r\n' +
        'event: token\r\ndata: {"content":"parser"}\r\n\r\n' +
        'event: message_end\r\ndata: {"content":"Robust parser","agent":"diary","metadata":{}}\r\n\r\n',
    ]);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(streamResponse(stream)));

    renderWithProviders(<ChatPage />);

    await user.type(screen.getByPlaceholderText("Ask anything..."), "Hi");
    await user.click(screen.getByRole("button", { name: /send message/i }));

    await waitFor(() => {
      expect(screen.getByText(/Robust parser/)).toBeInTheDocument();
    });
  });
});

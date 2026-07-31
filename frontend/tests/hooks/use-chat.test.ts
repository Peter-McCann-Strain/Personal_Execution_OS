import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { API_PATHS } from "@/api/generated/paths";

// ---- Mock stores before importing the hook ----

const mockAddMessage = vi.fn();
const mockUpdateLastMessage = vi.fn();
const mockPatchLastMessage = vi.fn();
const mockSetStreaming = vi.fn();
const mockSetActiveAgent = vi.fn();
const mockClearMessages = vi.fn();
const mockFinalizeLastMessage = vi.fn();
const mockStoreState = {
  messages: [] as unknown[],
  isStreaming: false,
};
const mockAppState = {
  apiKey: "test-api-key",
};

vi.mock("@/stores/chat", () => ({
  useChatStore: Object.assign(
    // The hook itself — called as useChatStore() and useChatStore((s) => ...)
    vi.fn((selector?: (s: unknown) => unknown) => {
      const state = {
        messages: mockStoreState.messages,
        isStreaming: mockStoreState.isStreaming,
        addMessage: mockAddMessage,
        updateLastMessage: mockUpdateLastMessage,
        patchLastMessage: mockPatchLastMessage,
        setStreaming: mockSetStreaming,
        setActiveAgent: mockSetActiveAgent,
        clearMessages: mockClearMessages,
        finalizeLastMessage: mockFinalizeLastMessage,
      };
      return selector ? selector(state) : state;
    }),
    {
      // Static method on the store
      getState: () => ({
        finalizeLastMessage: mockFinalizeLastMessage,
      }),
    },
  ),
}));

vi.mock("@/stores/app", () => ({
  useAppStore: vi.fn((selector?: (s: unknown) => unknown) => {
    const state = { apiKey: mockAppState.apiKey };
    return selector ? selector(state) : state;
  }),
}));

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}));

// Import after mocks are in place
import { useChat } from "@/hooks/use-chat";
import { toast } from "sonner";

// ---- Helpers ----

/** Build a ReadableStream that emits SSE-formatted chunks */
function createSSEStream(events: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const event of events) {
        controller.enqueue(encoder.encode(event));
      }
      controller.close();
    },
  });
}

function mockFetchResponse(body: ReadableStream<Uint8Array>, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    body,
    text: () => Promise.resolve("Error body"),
    headers: new Headers(),
    redirected: false,
    statusText: status === 200 ? "OK" : "Error",
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

// ---- Tests ----

describe("useChat", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockStoreState.messages = [];
    mockStoreState.isStreaming = false;
    mockAppState.apiKey = "test-api-key";
    // Mock crypto.randomUUID
    vi.stubGlobal("crypto", {
      ...globalThis.crypto,
      randomUUID: () => "test-uuid-1234",
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns expected interface", () => {
    const { result } = renderHook(() => useChat());

    expect(result.current).toHaveProperty("messages");
    expect(result.current).toHaveProperty("isStreaming");
    expect(result.current).toHaveProperty("inputValue");
    expect(result.current).toHaveProperty("setInputValue");
    expect(result.current).toHaveProperty("sendMessage");
    expect(result.current).toHaveProperty("stopStreaming");
    expect(result.current).toHaveProperty("clearMessages");
    expect(result.current).toHaveProperty("sensitiveMode");
    expect(result.current).toHaveProperty("suppressedSources");
    expect(result.current).toHaveProperty("toggleSensitiveMode");
    expect(result.current).toHaveProperty("toggleSuppressedSource");
  });

  it("stopStreaming is a no-op when no request is active", () => {
    const { result } = renderHook(() => useChat());

    expect(() => {
      result.current.stopStreaming();
    }).not.toThrow();
  });

  it("sendMessage calls fetch with correct URL, headers, and body", async () => {
    document.cookie = "peos_csrf=chat-csrf-token; Path=/";
    const stream = createSSEStream([
      'event: token\ndata: {"content":"Hi"}\n\n',
      'event: message_end\ndata: {"content":"Hi","agent":"diary","metadata":{}}\n\n',
    ]);

    const fetchMock = vi.fn().mockResolvedValue(mockFetchResponse(stream));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage("Hello world");
    });

    expect(fetchMock).toHaveBeenCalledOnce();

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe(API_PATHS.apiChatStream);
    expect(options.method).toBe("POST");
    expect(options.credentials).toBe("same-origin");
    expect(options.headers["Content-Type"]).toBe("application/json");
    expect(options.headers["X-API-Key"]).toBe("test-api-key");
    expect(options.headers["X-CSRF-Token"]).toBe("chat-csrf-token");

    const body = JSON.parse(options.body);
    expect(body.content).toBe("Hello world");
    expect(body.source).toBe("api");
    expect(body.sensitive_mode).toBe(false);
    expect(body.suppressed_sources).toEqual([]);
  });

  it("omits the api key header when no api key is configured", async () => {
    mockAppState.apiKey = "";
    const stream = createSSEStream([
      'event: message_end\ndata: {"content":"Hi","agent":"diary","metadata":{}}\n\n',
    ]);

    const fetchMock = vi.fn().mockResolvedValue(mockFetchResponse(stream));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage("Hello world");
    });

    const [, options] = fetchMock.mock.calls[0];
    expect(options.headers["X-API-Key"]).toBeUndefined();
  });

  it("adds user and assistant messages to the store", async () => {
    const stream = createSSEStream([
      'event: token\ndata: {"content":"Response"}\n\n',
      'event: message_end\ndata: {"content":"Response","agent":"diary","metadata":{}}\n\n',
    ]);

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockFetchResponse(stream)));

    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage("Test message");
    });

    // First call: user message
    expect(mockAddMessage).toHaveBeenCalledTimes(2);
    const userMsg = mockAddMessage.mock.calls[0][0];
    expect(userMsg.role).toBe("user");
    expect(userMsg.content).toBe("Test message");

    // Second call: assistant placeholder
    const assistantMsg = mockAddMessage.mock.calls[1][0];
    expect(assistantMsg.role).toBe("assistant");
    expect(assistantMsg.content).toBe("");
    expect(assistantMsg.isStreaming).toBe(true);
  });

  it("accumulates streamed content via updateLastMessage", async () => {
    const stream = createSSEStream([
      'event: token\ndata: {"content":"Hello"}\n\n',
      'event: token\ndata: {"content":" world"}\n\n',
      'event: message_end\ndata: {"content":"Hello world","agent":"diary","metadata":{}}\n\n',
    ]);

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockFetchResponse(stream)));

    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage("Hi");
    });

    // Content is accumulated: first "Hello", then "Hello world"
    expect(mockUpdateLastMessage).toHaveBeenCalledWith("Hello");
    expect(mockUpdateLastMessage).toHaveBeenCalledWith("Hello world");
  });

  it("sets activeAgent when the stream includes an agent field", async () => {
    const stream = createSSEStream([
      'event: agent\ndata: {"agent":"diary"}\n\n',
      'event: message_end\ndata: {"content":"Hi","agent":"diary","metadata":{}}\n\n',
    ]);

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockFetchResponse(stream)));

    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage("journal entry");
    });

    expect(mockSetActiveAgent).toHaveBeenCalledWith("diary");
  });

  it("handles HTTP error responses", async () => {
    const errorResponse = {
      ok: false,
      status: 500,
      text: () => Promise.resolve("Internal Server Error"),
      body: null,
      headers: new Headers(),
      redirected: false,
      statusText: "Internal Server Error",
      type: "basic" as ResponseType,
      url: "",
      clone: () => ({}) as Response,
      arrayBuffer: () => Promise.resolve(new ArrayBuffer(0)),
      blob: () => Promise.resolve(new Blob()),
      formData: () => Promise.resolve(new FormData()),
      json: () => Promise.resolve({}),
      bytes: () => Promise.resolve(new Uint8Array()),
    } as Response;

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(errorResponse));

    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage("test");
    });

    // Should show error toast
    expect(toast.error).toHaveBeenCalledWith("Message failed", {
      description: "Chat failed (500): Internal Server Error",
      duration: 8000,
    });

    expect(mockUpdateLastMessage).toHaveBeenCalledWith("Chat failed (500): Internal Server Error");
    expect(mockPatchLastMessage).toHaveBeenCalledWith({
      metadata: {
        error: true,
        error_message: "Chat failed (500): Internal Server Error",
      },
    });
  });

  it("sets and clears streaming state", async () => {
    const stream = createSSEStream([
      'event: token\ndata: {"content":"ok"}\n\n',
      'event: message_end\ndata: {"content":"ok","agent":"diary","metadata":{}}\n\n',
    ]);

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockFetchResponse(stream)));

    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage("test");
    });

    // setStreaming(true) at start, setStreaming(false) in finally
    expect(mockSetStreaming).toHaveBeenCalledWith(true);
    expect(mockSetStreaming).toHaveBeenCalledWith(false);

    // Order: true first, then false
    const calls = mockSetStreaming.mock.calls.map((c) => c[0]);
    expect(calls.indexOf(true)).toBeLessThan(calls.lastIndexOf(false));
  });

  it("calls finalizeLastMessage in finally block", async () => {
    const stream = createSSEStream([
      'event: token\ndata: {"content":"done"}\n\n',
      'event: message_end\ndata: {"content":"done","agent":"diary","metadata":{}}\n\n',
    ]);

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockFetchResponse(stream)));

    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage("test");
    });

    expect(mockFinalizeLastMessage).toHaveBeenCalled();
  });

  it("clears activeAgent in finally block", async () => {
    const stream = createSSEStream([
      'event: agent\ndata: {"agent":"memory"}\n\n',
      'event: token\ndata: {"content":"x"}\n\n',
      'event: message_end\ndata: {"content":"x","agent":"memory","metadata":{}}\n\n',
    ]);

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockFetchResponse(stream)));

    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage("test");
    });

    // Last call to setActiveAgent should be null (cleanup)
    const agentCalls = mockSetActiveAgent.mock.calls;
    expect(agentCalls[agentCalls.length - 1][0]).toBeNull();
  });

  it("stopStreaming aborts the fetch via AbortController", async () => {
    // Capture the signal passed to fetch so we can verify it was aborted
    let capturedSignal: AbortSignal | undefined;

    // Create a stream whose read() blocks until the signal is aborted
    new ReadableStream<Uint8Array>({
      start() {
        // Do not enqueue or close — the read will block
      },
      cancel() {
        // Called when the stream is cancelled (via abort)
      },
    });

    // Mock fetch to capture the signal and return a response whose body
    // read() will reject when aborted
    const fetchMock = vi.fn().mockImplementation((_url: string, options: RequestInit) => {
      capturedSignal = options.signal as AbortSignal;

      // Create a reader-like body that respects the abort signal
      const body = new ReadableStream<Uint8Array>({
        start(controller) {
          // When the signal fires, error the stream to unblock the reader
          capturedSignal!.addEventListener("abort", () => {
            try {
              controller.error(capturedSignal!.reason ?? new DOMException("Aborted", "AbortError"));
            } catch {
              // controller may already be closed
            }
          });
        },
      });

      return Promise.resolve(mockFetchResponse(body));
    });

    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useChat());

    // Start send (will block on reader.read())
    let sendPromise: Promise<void> | undefined;
    act(() => {
      sendPromise = result.current.sendMessage("long request");
    });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());

    // Now abort
    act(() => {
      result.current.stopStreaming();
    });

    // The promise should resolve (abort path)
    await act(async () => {
      await sendPromise;
    });

    // The signal should have been aborted
    expect(capturedSignal?.aborted).toBe(true);
    // Streaming should be turned off in the finally block
    expect(mockSetStreaming).toHaveBeenCalledWith(false);
  });

  it("does not send when content is empty or whitespace-only", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage("");
    });

    await act(async () => {
      await result.current.sendMessage("   ");
    });

    expect(fetchMock).not.toHaveBeenCalled();
    expect(mockAddMessage).not.toHaveBeenCalled();
  });

  it("does not send when a stream is already in progress", async () => {
    mockStoreState.isStreaming = true;
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage("blocked");
    });

    expect(fetchMock).not.toHaveBeenCalled();
    expect(mockAddMessage).not.toHaveBeenCalled();
  });

  it("surfaces an explicit error when no content is received", async () => {
    const stream = createSSEStream([
      'event: message_end\ndata: {"content":"","agent":"diary","metadata":{}}\n\n',
    ]);

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockFetchResponse(stream)));

    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage("hello");
    });

    expect(mockUpdateLastMessage).toHaveBeenCalledWith("Assistant returned an empty response.");
  });

  it("surfaces an explicit error when the streaming response has no readable body", async () => {
    const response = {
      ok: true,
      status: 200,
      body: null,
      text: () => Promise.resolve(""),
      headers: new Headers(),
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

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));

    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage("hello");
    });

    expect(mockUpdateLastMessage).toHaveBeenCalledWith("Assistant returned an empty response.");
  });

  it("handles SSE error payload from the server", async () => {
    const stream = createSSEStream(['event: error\ndata: {"error":"Rate limit exceeded"}\n\n']);

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockFetchResponse(stream)));

    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage("test");
    });

    expect(toast.error).toHaveBeenCalledWith("Message failed", {
      description: "Rate limit exceeded",
      duration: 8000,
    });
  });

  it("uses an explicit streaming error when the SSE error payload is empty", async () => {
    const stream = createSSEStream(["event: error\ndata: {}\n\n"]);

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockFetchResponse(stream)));

    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage("test");
    });

    expect(toast.error).toHaveBeenCalledWith("Message failed", {
      description: "Unknown streaming error",
      duration: 8000,
    });
    expect(mockUpdateLastMessage).toHaveBeenCalledWith("Unknown streaming error");
  });

  it("patches the last assistant message with metadata from message_end", async () => {
    const stream = createSSEStream([
      'event: tool_status\ndata: {"tool_calls":[{"name":"tavily-search__search"}],"tool_count":1,"errors":0}\n\n',
      'event: message_end\ndata: {"content":"Found it","agent":"tools","metadata":{"tool_calls":[{"name":"tavily-search__search"}]}}\n\n',
    ]);

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockFetchResponse(stream)));

    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage("search the web");
    });

    expect(mockPatchLastMessage).toHaveBeenCalledWith({
      metadata: {
        tool_calls: [{ name: "tavily-search__search" }],
        tool_count: 1,
        errors: 0,
      },
    });

    expect(mockPatchLastMessage).toHaveBeenCalledWith({
      agent: "tools",
      metadata: {
        tool_calls: [{ name: "tavily-search__search" }],
      },
    });
  });

  it("handles split SSE chunks and tool status without explicit tool calls", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('event: token\ndata: {"content":"Hel'));
        controller.enqueue(
          encoder.encode('lo"}\n\nevent: tool_status\ndata: {"tool_count":2,"errors":1}\n\n'),
        );
        controller.enqueue(
          encoder.encode(
            'event: message_end\ndata: {"content":"Hello","metadata":{"request_id":"req-2"}}\n\n',
          ),
        );
        controller.close();
      },
    });

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockFetchResponse(stream)));

    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage("stream please");
    });

    expect(mockUpdateLastMessage).toHaveBeenCalledWith("Hello");
    expect(mockPatchLastMessage).toHaveBeenCalledWith({
      metadata: {
        tool_calls: [],
        tool_count: 2,
        errors: 1,
      },
    });
    expect(mockPatchLastMessage).toHaveBeenCalledWith({
      agent: undefined,
      metadata: { request_id: "req-2" },
    });
  });

  it("ignores keepalive, done, and unknown SSE events before the final message", async () => {
    const stream = createSSEStream([
      ": ping\n\n",
      "data: [DONE]\n\n",
      'data: {"content":"ignored"}\n\n',
      'event: message_end\ndata: {"content":"Final","agent":"diary","metadata":{"request_id":"req-3"}}\n\n',
    ]);

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockFetchResponse(stream)));

    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage("hello");
    });

    expect(mockUpdateLastMessage).toHaveBeenCalledWith("Final");
    expect(mockPatchLastMessage).toHaveBeenCalledWith({
      agent: "diary",
      metadata: { request_id: "req-3" },
    });
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("renders all tokens when the entire SSE stream arrives in one chunk", async () => {
    // Production scenario: uvicorn flushes every SSE event in a single TCP
    // packet for short responses. The reader sees one big chunk containing
    // message_start + agent + token + token + message_end. Every token
    // must still be appended to the assistant bubble's content.
    const stream = createSSEStream([
      'event: message_start\ndata: {"request_id":"req-1","source":"api"}\n\n' +
        'event: agent\ndata: {"agent":"diary"}\n\n' +
        'event: token\ndata: {"content":"Still "}\n\n' +
        'event: token\ndata: {"content":"here."}\n\n' +
        'event: message_end\ndata: {"content":"Still here.","agent":"diary","metadata":{"request_id":"req-1"}}\n\n',
    ]);

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockFetchResponse(stream)));

    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage("Are you there?");
    });

    expect(mockUpdateLastMessage).toHaveBeenCalledWith("Still ");
    expect(mockUpdateLastMessage).toHaveBeenCalledWith("Still here.");
  });

  it("normalises CRLF separators emitted by reverse proxies", async () => {
    const stream = createSSEStream([
      'event: token\r\ndata: {"content":"crlf "}\r\n\r\n' +
        'event: token\r\ndata: {"content":"works"}\r\n\r\n' +
        'event: message_end\r\ndata: {"content":"crlf works","agent":"diary","metadata":{}}\r\n\r\n',
    ]);

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockFetchResponse(stream)));

    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage("hi");
    });

    expect(mockUpdateLastMessage).toHaveBeenCalledWith("crlf works");
  });

  it("skips a malformed event without losing later tokens", async () => {
    const stream = createSSEStream([
      "event: token\ndata: not-json\n\n" +
        'event: token\ndata: {"content":"survived"}\n\n' +
        'event: message_end\ndata: {"content":"survived","agent":"diary","metadata":{}}\n\n',
    ]);

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockFetchResponse(stream)));

    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage("hi");
    });

    // The bad payload is dropped; the good token still hits the store.
    expect(mockUpdateLastMessage).toHaveBeenCalledWith("survived");
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("handles message_end without an agent and non-Error failures", async () => {
    const stream = createSSEStream([
      'event: message_end\ndata: {"content":"Finished","metadata":{"request_id":"req-1"}}\n\n',
    ]);

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockFetchResponse(stream)));

    const { result, rerender } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage("hello");
    });

    expect(mockSetActiveAgent).not.toHaveBeenCalledWith(undefined);
    expect(mockPatchLastMessage).toHaveBeenCalledWith({
      agent: undefined,
      metadata: { request_id: "req-1" },
    });

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue("socket closed"));
    rerender();

    await act(async () => {
      await result.current.sendMessage("retry");
    });

    expect(toast.error).toHaveBeenCalledWith("Message failed", {
      description: "Failed to send message",
      duration: 8000,
    });
  });
});

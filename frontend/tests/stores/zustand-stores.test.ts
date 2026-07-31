import { beforeEach, describe, expect, test, vi } from "vitest";

import { useAppStore } from "@/stores/app";
import { useChatStore } from "@/stores/chat";
import type { ChatMessage, Email, Entity, EntityRelationship } from "@/types";

function makeAssistantMessage(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: "assistant-1",
    role: "assistant",
    content: "Hello",
    timestamp: new Date("2026-04-07T12:00:00Z").toISOString(),
    isStreaming: true,
    ...overrides,
  };
}

function resetAppStore() {
  useAppStore.setState({
    sidebarCollapsed: false,
    rightPanelOpen: false,
    rightPanelContent: null,
    inspectedEmail: null,
    inspectedEntity: null,
    theme: "dark",
    commandPaletteOpen: false,
    apiKey: "",
    profileSettings: {
      displayName: "Owner",
      timezone: "UTC",
      workStart: "09:00",
      workEnd: "17:30",
    },
  });
  useAppStore.persist.clearStorage();
  sessionStorage.removeItem("api_key");
  document.documentElement.removeAttribute("data-theme");
}

function resetChatStore() {
  useChatStore.setState({
    messages: [],
    isStreaming: false,
    activeAgent: null,
  });
  localStorage.removeItem("assistant-chat-store");
}

function mockMatchMedia(matches: boolean) {
  return {
    matches,
    media: "(prefers-color-scheme: dark)",
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  };
}

describe("useAppStore", () => {
  beforeEach(() => {
    resetAppStore();
    vi.clearAllMocks();
  });

  test("toggles and sets sidebar state", () => {
    useAppStore.getState().toggleSidebar();
    expect(useAppStore.getState().sidebarCollapsed).toBe(true);

    useAppStore.getState().setSidebarCollapsed(false);
    expect(useAppStore.getState().sidebarCollapsed).toBe(false);
  });

  test("opens and closes the right panel", () => {
    useAppStore.getState().openRightPanel("workspace");
    expect(useAppStore.getState().rightPanelOpen).toBe(true);
    expect(useAppStore.getState().rightPanelContent).toBe("workspace");

    useAppStore.getState().openRightPanel("email");
    expect(useAppStore.getState().rightPanelOpen).toBe(true);
    expect(useAppStore.getState().rightPanelContent).toBe("email");

    useAppStore.getState().closeRightPanel();
    expect(useAppStore.getState().rightPanelOpen).toBe(false);
    expect(useAppStore.getState().rightPanelContent).toBeNull();
  });

  test("tracks live inspector selections without persisting them", () => {
    const email: Email = {
      id: "email-1",
      threadId: "thread-1",
      snippet: "Snippet",
      headers: { From: "Ada <ada@example.com>", Subject: "Subject" },
      body: "Body",
      labelIds: ["INBOX"],
      internalDate: null,
    };
    const entity: Entity = {
      id: "entity-1",
      name: "Ada Lovelace",
      entity_type: "PERSON",
      canonical_name: null,
      mention_count: 3,
      first_seen: null,
      last_seen: null,
      metadata: {},
      created_at: "2026-04-01T10:00:00Z",
    };
    const relationship: EntityRelationship = {
      id: "rel-1",
      source_entity_id: "entity-1",
      target_entity_id: "entity-2",
      relationship_type: "collaborated_with",
      valid_from: null,
      valid_to: null,
    };

    useAppStore.getState().setInspectedEmail(email);
    useAppStore.getState().setInspectedEntity({
      entity,
      relationships: [{ relationship, relatedEntity: entity }],
    });

    expect(useAppStore.getState().inspectedEmail?.id).toBe("email-1");
    expect(useAppStore.getState().inspectedEntity?.entity.id).toBe("entity-1");
    expect(useAppStore.persist.getOptions().partialize?.(useAppStore.getState())).toEqual({
      profileSettings: {
        displayName: "Owner",
        timezone: "UTC",
        workStart: "09:00",
        workEnd: "17:30",
      },
      sidebarCollapsed: false,
      theme: "dark",
    });
  });

  test("sets explicit theme directly on the document element", () => {
    useAppStore.getState().setTheme("light");

    expect(useAppStore.getState().theme).toBe("light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  test("resolves system theme using matchMedia", () => {
    vi.mocked(window.matchMedia).mockReturnValueOnce(mockMatchMedia(true));

    useAppStore.getState().setTheme("system");

    expect(useAppStore.getState().theme).toBe("system");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  test("resolves system theme to light and persists only the intended fields", () => {
    vi.mocked(window.matchMedia).mockReturnValueOnce(mockMatchMedia(false));

    useAppStore.getState().setTheme("system");
    useAppStore.getState().setSidebarCollapsed(true);
    useAppStore.getState().setCommandPaletteOpen(true);
    useAppStore.getState().openRightPanel("artifact");

    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(useAppStore.persist.getOptions().partialize?.(useAppStore.getState())).toEqual({
      profileSettings: {
        displayName: "Owner",
        timezone: "UTC",
        workStart: "09:00",
        workEnd: "17:30",
      },
      sidebarCollapsed: true,
      theme: "system",
    });
  });

  test("controls command palette and stores the api key for the active session", () => {
    useAppStore.getState().setCommandPaletteOpen(true);
    useAppStore.getState().setApiKey("secret-key");

    expect(useAppStore.getState().commandPaletteOpen).toBe(true);
    expect(useAppStore.getState().apiKey).toBe("secret-key");
    expect(sessionStorage.getItem("api_key")).toBe("secret-key");
    expect(localStorage.getItem("api_key")).toBeNull();
  });
});

describe("useChatStore", () => {
  beforeEach(() => {
    resetChatStore();
  });

  test("adds assistant messages and updates the last assistant message", () => {
    useChatStore.getState().addMessage(makeAssistantMessage());
    useChatStore.getState().updateLastMessage("Updated");

    expect(useChatStore.getState().messages).toHaveLength(1);
    expect(useChatStore.getState().messages[0].content).toBe("Updated");
  });

  test("does not update a non-assistant message", () => {
    useChatStore
      .getState()
      .addMessage(makeAssistantMessage({ id: "user-1", role: "user", content: "User input" }));
    useChatStore.getState().updateLastMessage("Ignored");

    expect(useChatStore.getState().messages[0].content).toBe("User input");
  });

  test("patches and finalizes the last assistant message", () => {
    useChatStore.getState().addMessage(makeAssistantMessage());
    useChatStore.getState().patchLastMessage({
      agent: "tools",
      metadata: { source: "mcp" },
    });
    useChatStore.getState().finalizeLastMessage();

    const [message] = useChatStore.getState().messages;
    expect(message.agent).toBe("tools");
    expect(message.metadata).toEqual({ source: "mcp" });
    expect(message.isStreaming).toBe(false);
  });

  test("leaves non-assistant messages unchanged when patching or finalizing", () => {
    useChatStore
      .getState()
      .addMessage(makeAssistantMessage({ id: "system-1", role: "system", content: "System note" }));
    useChatStore.getState().patchLastMessage({ agent: "review" });
    useChatStore.getState().finalizeLastMessage();

    const [message] = useChatStore.getState().messages;
    expect(message.agent).toBeUndefined();
    expect(message.isStreaming).toBe(true);
  });

  test("sets streaming flags, active agent, and clears messages without browser persistence", () => {
    useChatStore.getState().addMessage(makeAssistantMessage());
    useChatStore.getState().setStreaming(true);
    useChatStore.getState().setActiveAgent("memory");

    expect(useChatStore.getState().isStreaming).toBe(true);
    expect(useChatStore.getState().activeAgent).toBe("memory");

    useChatStore.getState().clearMessages();
    expect(useChatStore.getState().messages).toEqual([]);
    expect(localStorage.getItem("assistant-chat-store")).toBeNull();
  });
});

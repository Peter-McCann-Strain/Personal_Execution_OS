import { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearThisDevice } from "@/lib/device-data";
import { useAppStore } from "@/stores/app";
import { useChatStore } from "@/stores/chat";

const mocks = vi.hoisted(() => ({
  disconnectPush: vi.fn(),
  logout: vi.fn(),
}));

const originalServiceWorker = navigator.serviceWorker;

vi.mock("@/api/auth", () => ({
  logoutCurrentSession: mocks.logout,
}));

vi.mock("@/lib/web-push", () => ({
  disconnectCurrentBrowserPushSubscription: mocks.disconnectPush,
}));

describe("clearThisDevice", () => {
  beforeEach(() => {
    mocks.disconnectPush.mockReset().mockResolvedValue(undefined);
    mocks.logout.mockReset().mockResolvedValue(undefined);
    localStorage.setItem("assistant-app-store", "saved");
    localStorage.setItem("assistant-chat-store", "legacy chat");
    sessionStorage.setItem("api_key", "development-key");
    sessionStorage.setItem("native_notification_seen_v1", "true");
    useChatStore.setState({
      messages: [
        {
          id: "message-1",
          role: "user",
          content: "private chat",
          timestamp: new Date().toISOString(),
        },
      ],
      isStreaming: false,
      activeAgent: null,
    });
    useAppStore.setState({
      sidebarCollapsed: true,
      rightPanelOpen: true,
      rightPanelContent: "workspace",
      apiKey: "development-key",
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    Object.defineProperty(navigator, "serviceWorker", {
      value: originalServiceWorker,
      configurable: true,
    });
  });

  it("revokes remote access and clears browser-held application data", async () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(["private"], { secret: true });

    const result = await clearThisDevice(queryClient, { unregisterServiceWorker: false });

    expect(result.warnings).toEqual([]);
    expect(mocks.disconnectPush).toHaveBeenCalledOnce();
    expect(mocks.logout).toHaveBeenCalledOnce();
    expect(queryClient.getQueryData(["private"])).toBeUndefined();
    expect(useChatStore.getState().messages).toEqual([]);
    expect(useAppStore.getState().rightPanelOpen).toBe(false);
    expect(useAppStore.getState().apiKey).toBe("");
    expect(localStorage.getItem("assistant-app-store")).toBeNull();
    expect(localStorage.getItem("assistant-chat-store")).toBeNull();
    expect(sessionStorage.getItem("api_key")).toBeNull();
    expect(sessionStorage.getItem("native_notification_seen_v1")).toBeNull();
  });

  it("continues local clearing and reports warnings when server cleanup fails", async () => {
    mocks.disconnectPush.mockRejectedValue(new Error("push unavailable"));
    mocks.logout.mockRejectedValue(new Error("session unavailable"));
    const queryClient = new QueryClient();
    queryClient.setQueryData(["private"], { secret: true });

    const result = await clearThisDevice(queryClient, { unregisterServiceWorker: false });

    expect(result.warnings).toEqual([
      "The browser push subscription or its server record could not be fully removed.",
      "The server session cookie could not be revoked.",
    ]);
    expect(queryClient.getQueryData(["private"])).toBeUndefined();
    expect(useChatStore.getState().messages).toEqual([]);
    expect(localStorage.getItem("assistant-app-store")).toBeNull();
  });

  it("clears offline caches and unregisters every installed worker when requested", async () => {
    const unregisterFirst = vi.fn().mockResolvedValue(true);
    const unregisterSecond = vi.fn().mockResolvedValue(true);
    Object.defineProperty(navigator, "serviceWorker", {
      value: {
        getRegistrations: vi
          .fn()
          .mockResolvedValue([{ unregister: unregisterFirst }, { unregister: unregisterSecond }]),
      },
      configurable: true,
    });
    const deleteCache = vi.fn().mockResolvedValue(true);
    vi.stubGlobal("caches", {
      keys: vi.fn().mockResolvedValue(["runtime", "assets"]),
      delete: deleteCache,
    });

    const result = await clearThisDevice(new QueryClient(), {
      unregisterServiceWorker: true,
    });

    expect(result.warnings).toEqual([]);
    expect(deleteCache).toHaveBeenCalledWith("runtime");
    expect(deleteCache).toHaveBeenCalledWith("assets");
    expect(unregisterFirst).toHaveBeenCalledOnce();
    expect(unregisterSecond).toHaveBeenCalledOnce();
  });

  it("reports cache and partial service-worker cleanup failures independently", async () => {
    Object.defineProperty(navigator, "serviceWorker", {
      value: {
        getRegistrations: vi
          .fn()
          .mockResolvedValue([
            { unregister: vi.fn().mockResolvedValue(true) },
            { unregister: vi.fn().mockResolvedValue(false) },
          ]),
      },
      configurable: true,
    });
    vi.stubGlobal("caches", {
      keys: vi.fn().mockRejectedValue(new Error("cache storage unavailable")),
      delete: vi.fn(),
    });

    const result = await clearThisDevice(new QueryClient(), {
      unregisterServiceWorker: true,
    });

    expect(result.warnings).toContain("The browser's offline cache could not be fully cleared.");
    expect(result.warnings).toContain(
      "The installed web app service worker could not be fully unregistered.",
    );
  });

  it("continues clearing when in-memory cache or persisted preferences throw", async () => {
    const queryClient = new QueryClient();
    vi.spyOn(queryClient, "clear").mockImplementation(() => {
      throw new Error("query cache unavailable");
    });
    vi.spyOn(useAppStore.persist, "clearStorage").mockImplementation(() => {
      throw new Error("storage unavailable");
    });

    const result = await clearThisDevice(queryClient, {
      unregisterServiceWorker: false,
    });

    expect(result.warnings).toContain("The in-memory request cache could not be cleared.");
    expect(result.warnings).toContain("The saved application preferences could not be cleared.");
    expect(useChatStore.getState().messages).toEqual([]);
    expect(sessionStorage.getItem("api_key")).toBeNull();
  });

  it("falls back to UTC when the browser cannot resolve a local timezone", async () => {
    vi.spyOn(Intl, "DateTimeFormat").mockReturnValue({
      resolvedOptions: () => ({ timeZone: "" }),
    } as Intl.DateTimeFormat);

    await clearThisDevice(new QueryClient(), {
      unregisterServiceWorker: false,
    });

    expect(useAppStore.getState().profileSettings.timezone).toBe("UTC");
  });
});

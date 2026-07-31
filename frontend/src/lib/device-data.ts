import type { QueryClient } from "@tanstack/react-query";
import { logoutCurrentSession } from "@/api/auth";
import { disconnectCurrentBrowserPushSubscription } from "@/lib/web-push";
import { useAppStore } from "@/stores/app";
import { useChatStore } from "@/stores/chat";

export interface ClearThisDeviceResult {
  warnings: string[];
}

export async function clearThisDevice(
  queryClient: QueryClient,
  options: { unregisterServiceWorker: boolean },
): Promise<ClearThisDeviceResult> {
  const warnings: string[] = [];

  const attempt = async (action: () => unknown | Promise<unknown>, warning: string) => {
    try {
      await action();
    } catch {
      warnings.push(warning);
    }
  };

  await attempt(
    () => disconnectCurrentBrowserPushSubscription(),
    "The browser push subscription or its server record could not be fully removed.",
  );
  await attempt(() => logoutCurrentSession(), "The server session cookie could not be revoked.");
  await attempt(() => queryClient.clear(), "The in-memory request cache could not be cleared.");
  await attempt(
    () => useChatStore.getState().clearMessages(),
    "The in-memory chat could not be cleared.",
  );
  await attempt(() => {
    useAppStore.setState({
      sidebarCollapsed: false,
      mobileSidebarOpen: false,
      rightPanelOpen: false,
      rightPanelContent: null,
      inspectedEmail: null,
      inspectedEntity: null,
      inspectedAgentRunId: null,
      profileSettings: {
        displayName: "Owner",
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
        workStart: "09:00",
        workEnd: "17:30",
      },
      commandPaletteOpen: false,
      apiKey: "",
      runtimeStreamStatus: "idle",
    });
  }, "The in-memory application state could not be reset.");
  await attempt(
    () => useAppStore.persist.clearStorage(),
    "The saved application preferences could not be cleared.",
  );

  await attempt(() => {
    if (typeof localStorage !== "undefined") {
      localStorage.removeItem("assistant-app-store");
      localStorage.removeItem("assistant-chat-store");
    }
    if (typeof sessionStorage !== "undefined") {
      sessionStorage.removeItem("api_key");
      sessionStorage.removeItem("native_notification_seen_v1");
    }
  }, "Some browser storage could not be cleared.");

  await attempt(async () => {
    if (typeof caches !== "undefined") {
      const cacheNames = await caches.keys();
      await Promise.all(cacheNames.map((cacheName) => caches.delete(cacheName)));
    }
  }, "The browser's offline cache could not be fully cleared.");

  if (
    options.unregisterServiceWorker &&
    typeof navigator !== "undefined" &&
    "serviceWorker" in navigator
  ) {
    await attempt(async () => {
      const registrations = await navigator.serviceWorker.getRegistrations();
      const results = await Promise.all(
        registrations.map((registration) => registration.unregister()),
      );
      if (results.some((removed) => !removed)) {
        throw new Error("A service worker registration was not removed.");
      }
    }, "The installed web app service worker could not be fully unregistered.");
  }

  return { warnings };
}

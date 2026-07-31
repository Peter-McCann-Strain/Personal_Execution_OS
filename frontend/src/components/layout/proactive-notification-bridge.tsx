import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getAgentRuns } from "@/api/agent-runs";
import {
  getNotifications,
  getWebPushConfig,
  registerWebPushSubscription,
} from "@/api/notifications";
import { useAppStore } from "@/stores/app";

const STORAGE_KEY = "native_notification_seen_v1";
const PERMISSION_EVENT = "assistant-notification-permission-change";

function getNotificationPermission(): NotificationPermission | "unsupported" {
  if (typeof Notification === "undefined") {
    return "unsupported";
  }
  return Notification.permission;
}

function supportsWebPush(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof navigator !== "undefined" &&
    "serviceWorker" in navigator &&
    "PushManager" in window
  );
}

function urlBase64ToApplicationServerKey(base64String: string): ArrayBuffer {
  const padded = `${base64String}${"=".repeat((4 - (base64String.length % 4)) % 4)}`;
  const normalized = padded.replace(/-/g, "+").replace(/_/g, "/");
  const decoded = window.atob(normalized);
  return Uint8Array.from(decoded, (char) => char.charCodeAt(0)).buffer as ArrayBuffer;
}

function readSeenIds(): Set<string> {
  if (typeof window === "undefined") {
    return new Set();
  }
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return new Set();
    }
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? new Set(parsed.map(String)) : new Set();
  } catch {
    return new Set();
  }
}

function persistSeenIds(ids: Set<string>): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(Array.from(ids)));
  } catch {
    // Ignore storage failures; they should not break the app shell.
  }
}

function showNotification(title: string, body: string, url: string, tag: string): void {
  if (typeof Notification === "undefined" || Notification.permission !== "granted") {
    return;
  }
  const notification = new Notification(title, { body, tag });
  notification.onclick = () => {
    window.focus();
    window.location.assign(url);
    notification.close();
  };
}

async function ensureWebPushRegistration(publicKey: string): Promise<void> {
  if (!supportsWebPush()) {
    throw new Error("Web push is not supported in this browser.");
  }

  const registration = await navigator.serviceWorker.ready;
  let subscription = await registration.pushManager.getSubscription();
  if (subscription == null) {
    subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToApplicationServerKey(publicKey),
    });
  }

  const payload = subscription.toJSON();
  const auth = payload.keys?.auth;
  const p256dh = payload.keys?.p256dh;
  if (!payload.endpoint || !auth || !p256dh) {
    throw new Error("Browser push subscription is missing required keys.");
  }

  await registerWebPushSubscription({
    endpoint: payload.endpoint,
    expiration_time: payload.expirationTime ?? undefined,
    keys: {
      auth,
      p256dh,
    },
    metadata: {
      client: "web_app",
      platform: navigator.platform || "",
      language: navigator.language || "",
    },
  });
}

function ProactiveNotificationBridge() {
  const queryClient = useQueryClient();
  const runtimeStreamStatus = useAppStore((state) => state.runtimeStreamStatus);
  const [permission, setPermission] = useState<NotificationPermission | "unsupported">(
    getNotificationPermission(),
  );
  const [webPushActive, setWebPushActive] = useState(false);
  const seenIdsRef = useRef<Set<string>>(readSeenIds());
  const registrationAttemptRef = useRef<string | null>(null);
  const primedRef = useRef<{ notifications: boolean; approvals: boolean }>({
    notifications: false,
    approvals: false,
  });

  useEffect(() => {
    const refreshPermission = () => setPermission(getNotificationPermission());
    window.addEventListener("focus", refreshPermission);
    document.addEventListener("visibilitychange", refreshPermission);
    window.addEventListener(PERMISSION_EVENT, refreshPermission);
    return () => {
      window.removeEventListener("focus", refreshPermission);
      document.removeEventListener("visibilitychange", refreshPermission);
      window.removeEventListener(PERMISSION_EVENT, refreshPermission);
    };
  }, []);

  const pushSupported = supportsWebPush();
  const webPushConfigQuery = useQuery({
    queryKey: ["notifications", "push", "config"],
    queryFn: () => getWebPushConfig(),
    enabled: permission === "granted" && pushSupported,
    staleTime: 60_000,
  });

  const registerMutation = useMutation({
    mutationFn: (publicKey: string) => ensureWebPushRegistration(publicKey),
    onSuccess: () => {
      setWebPushActive(true);
      queryClient.invalidateQueries({ queryKey: ["notifications", "push", "config"] });
      queryClient.invalidateQueries({ queryKey: ["notifications", "push", "subscriptions"] });
    },
    onError: () => {
      setWebPushActive(false);
    },
  });

  useEffect(() => {
    function deactivateWebPush() {
      queueMicrotask(() => setWebPushActive(false));
    }

    if (permission !== "granted") {
      deactivateWebPush();
      registrationAttemptRef.current = null;
      return;
    }
    if (!pushSupported) {
      deactivateWebPush();
      return;
    }
    const config = webPushConfigQuery.data;
    if (!config?.enabled || !config.public_key) {
      deactivateWebPush();
      return;
    }
    if (registerMutation.isPending || webPushActive) {
      return;
    }
    if (registrationAttemptRef.current === config.public_key) {
      return;
    }
    registrationAttemptRef.current = config.public_key;
    registerMutation.mutate(config.public_key);
  }, [permission, pushSupported, registerMutation, webPushActive, webPushConfigQuery.data]);

  const queriesEnabled = permission === "granted" && !webPushActive;
  const proactiveNotificationsQuery = useQuery({
    queryKey: ["native-bridge", "notifications"],
    queryFn: () => getNotifications({ limit: 6, category: "proactive", status: "unread" }),
    enabled: queriesEnabled,
    refetchInterval: runtimeStreamStatus === "live" ? false : 30_000,
  });
  const agentRunsQuery = useQuery({
    queryKey: ["native-bridge", "agent-runs"],
    queryFn: () => getAgentRuns({ limit: 8 }),
    enabled: queriesEnabled,
    refetchInterval: runtimeStreamStatus === "live" ? false : 30_000,
  });

  const pendingApprovals = useMemo(
    () => (agentRunsQuery.data?.items ?? []).filter((run) => run.pending_approvals > 0),
    [agentRunsQuery.data],
  );

  useEffect(() => {
    if (!queriesEnabled || !proactiveNotificationsQuery.data) {
      return;
    }
    const items = proactiveNotificationsQuery.data.items ?? [];
    if (!primedRef.current.notifications) {
      for (const item of items) {
        seenIdsRef.current.add(`notification:${item.id}`);
      }
      persistSeenIds(seenIdsRef.current);
      primedRef.current.notifications = true;
      return;
    }

    for (const item of items) {
      const key = `notification:${item.id}`;
      if (seenIdsRef.current.has(key)) {
        continue;
      }
      seenIdsRef.current.add(key);
      showNotification("Pulse update", item.message, "/pulse", key);
    }
    persistSeenIds(seenIdsRef.current);
  }, [proactiveNotificationsQuery.data, queriesEnabled]);

  useEffect(() => {
    if (!queriesEnabled || !agentRunsQuery.data) {
      return;
    }
    if (!primedRef.current.approvals) {
      for (const run of pendingApprovals) {
        seenIdsRef.current.add(`approval:${run.id}:${run.pending_approvals}`);
      }
      persistSeenIds(seenIdsRef.current);
      primedRef.current.approvals = true;
      return;
    }

    for (const run of pendingApprovals) {
      const key = `approval:${run.id}:${run.pending_approvals}`;
      if (seenIdsRef.current.has(key)) {
        continue;
      }
      seenIdsRef.current.add(key);
      const specialist = run.specialist ?? "assistant";
      showNotification(
        "Approval needed",
        `${specialist} run is waiting on ${run.pending_approvals} approval${run.pending_approvals === 1 ? "" : "s"}.`,
        "/pulse",
        key,
      );
    }
    persistSeenIds(seenIdsRef.current);
  }, [agentRunsQuery.data, pendingApprovals, queriesEnabled]);

  return null;
}

export { PERMISSION_EVENT, ProactiveNotificationBridge };

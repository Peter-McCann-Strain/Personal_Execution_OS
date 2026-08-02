import { QueryClientProvider } from "@tanstack/react-query";
import { act, render } from "@testing-library/react";
import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import { createTestQueryClient, renderWithProviders, waitFor } from "../../test-utils";
import { ProactiveNotificationBridge } from "@/components/layout/proactive-notification-bridge";

const mocks = vi.hoisted(() => ({
  getAgentRuns: vi.fn(),
  getNotifications: vi.fn(),
  getWebPushConfig: vi.fn(),
  notificationClose: vi.fn(),
  notificationsShown: [] as Array<{
    instance: { onclick: (() => void) | null };
    options?: NotificationOptions;
    title: string;
  }>,
  registerWebPushSubscription: vi.fn(),
}));

vi.mock("@/api/agent-runs", () => ({
  getAgentRuns: mocks.getAgentRuns,
}));

vi.mock("@/api/notifications", () => ({
  getNotifications: mocks.getNotifications,
  getWebPushConfig: mocks.getWebPushConfig,
  registerWebPushSubscription: mocks.registerWebPushSubscription,
}));

describe("ProactiveNotificationBridge", () => {
  const originalNotification = globalThis.Notification;
  const originalServiceWorker = navigator.serviceWorker;
  const originalPushManager = (window as Window & { PushManager?: unknown }).PushManager;

  beforeEach(() => {
    mocks.getAgentRuns.mockReset();
    mocks.getNotifications.mockReset();
    mocks.getWebPushConfig.mockReset();
    mocks.registerWebPushSubscription.mockReset();
    class MockNotification {
      static permission: NotificationPermission = "granted";
      onclick: (() => void) | null = null;
      constructor(
        public title: string,
        public options?: NotificationOptions,
      ) {
        mocks.notificationsShown.push({ instance: this, options, title });
      }
      close() {
        mocks.notificationClose();
      }
    }

    Object.defineProperty(globalThis, "Notification", {
      value: MockNotification,
      configurable: true,
    });
    Object.defineProperty(window, "PushManager", {
      value: class PushManager {},
      configurable: true,
    });
    Object.defineProperty(navigator, "serviceWorker", {
      value: {
        ready: Promise.resolve({
          pushManager: {
            getSubscription: vi.fn().mockResolvedValue({
              toJSON: () => ({
                endpoint: "https://push.example/subscription",
                expirationTime: null,
                keys: {
                  auth: "auth-key",
                  p256dh: "p256dh-key",
                },
              }),
            }),
          },
        }),
      },
      configurable: true,
    });

    mocks.getNotifications.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 6 });
    mocks.getAgentRuns.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 8 });
    mocks.getWebPushConfig.mockResolvedValue({
      enabled: true,
      public_key: "SGVsbG8",
      active_subscription_count: 0,
    });
    mocks.registerWebPushSubscription.mockResolvedValue({
      id: "subscription-1",
      status: "active",
    });
    mocks.notificationClose.mockReset();
    mocks.notificationsShown.length = 0;
    sessionStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    Object.defineProperty(globalThis, "Notification", {
      value: originalNotification,
      configurable: true,
    });
    Object.defineProperty(navigator, "serviceWorker", {
      value: originalServiceWorker,
      configurable: true,
    });
    Object.defineProperty(window, "PushManager", {
      value: originalPushManager,
      configurable: true,
    });
  });

  it("registers a browser push subscription when permission and config are ready", async () => {
    renderWithProviders(<ProactiveNotificationBridge />);

    await waitFor(() => {
      expect(mocks.registerWebPushSubscription).toHaveBeenCalledWith({
        endpoint: "https://push.example/subscription",
        expiration_time: undefined,
        keys: {
          auth: "auth-key",
          p256dh: "p256dh-key",
        },
        metadata: expect.objectContaining({
          client: "web_app",
        }),
      });
    });
  });

  it("does nothing when native notifications are denied", async () => {
    Object.defineProperty(globalThis.Notification, "permission", {
      value: "denied",
      configurable: true,
    });

    renderWithProviders(<ProactiveNotificationBridge />);
    await Promise.resolve();

    expect(mocks.getWebPushConfig).not.toHaveBeenCalled();
    expect(mocks.getNotifications).not.toHaveBeenCalled();
    expect(mocks.getAgentRuns).not.toHaveBeenCalled();
    expect(mocks.registerWebPushSubscription).not.toHaveBeenCalled();
  });

  it("treats browsers without the Notification API as unsupported", async () => {
    Reflect.deleteProperty(globalThis, "Notification");

    renderWithProviders(<ProactiveNotificationBridge />);
    await Promise.resolve();

    expect(mocks.getWebPushConfig).not.toHaveBeenCalled();
    expect(mocks.getNotifications).not.toHaveBeenCalled();
    expect(mocks.registerWebPushSubscription).not.toHaveBeenCalled();
  });

  it("falls back to in-app polling when web push is unsupported", async () => {
    Reflect.deleteProperty(window, "PushManager");

    renderWithProviders(<ProactiveNotificationBridge />);

    await waitFor(() => {
      expect(mocks.getNotifications).toHaveBeenCalledWith({
        limit: 6,
        category: "proactive",
        status: "unread",
      });
      expect(mocks.getAgentRuns).toHaveBeenCalledWith({ limit: 8 });
    });
    expect(mocks.getWebPushConfig).not.toHaveBeenCalled();
    expect(mocks.registerWebPushSubscription).not.toHaveBeenCalled();
  });

  it("creates a browser subscription when none exists", async () => {
    const subscribe = vi.fn().mockResolvedValue({
      toJSON: () => ({
        endpoint: "https://push.example/new-subscription",
        expirationTime: 1_800_000_000_000,
        keys: {
          auth: "new-auth",
          p256dh: "new-p256dh",
        },
      }),
    });
    Object.defineProperty(navigator, "serviceWorker", {
      value: {
        ready: Promise.resolve({
          pushManager: {
            getSubscription: vi.fn().mockResolvedValue(null),
            subscribe,
          },
        }),
      },
      configurable: true,
    });

    renderWithProviders(<ProactiveNotificationBridge />);

    await waitFor(() => expect(subscribe).toHaveBeenCalledOnce());
    expect(subscribe).toHaveBeenCalledWith({
      userVisibleOnly: true,
      applicationServerKey: expect.any(ArrayBuffer),
    });
    expect(mocks.registerWebPushSubscription).toHaveBeenCalledWith(
      expect.objectContaining({
        endpoint: "https://push.example/new-subscription",
        expiration_time: 1_800_000_000_000,
      }),
    );
  });

  it("rejects incomplete browser subscription payloads before server registration", async () => {
    Object.defineProperty(navigator, "serviceWorker", {
      value: {
        ready: Promise.resolve({
          pushManager: {
            getSubscription: vi.fn().mockResolvedValue({
              toJSON: () => ({
                endpoint: "https://push.example/incomplete",
                keys: { auth: "auth-only" },
              }),
            }),
          },
        }),
      },
      configurable: true,
    });

    renderWithProviders(<ProactiveNotificationBridge />);

    await waitFor(() => expect(mocks.getWebPushConfig).toHaveBeenCalledOnce());
    await waitFor(() => expect(mocks.registerWebPushSubscription).not.toHaveBeenCalled());
  });

  it("primes existing notifications and alerts only on newly observed items", async () => {
    mocks.getWebPushConfig.mockResolvedValue({
      enabled: false,
      public_key: null,
      active_subscription_count: 0,
    });
    mocks.getNotifications.mockResolvedValue({
      items: [{ id: "existing", message: "Already present" }],
      total: 1,
      offset: 0,
      limit: 6,
    });
    const queryClient = createTestQueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <ProactiveNotificationBridge />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(mocks.getNotifications).toHaveBeenCalledOnce());
    expect(mocks.notificationsShown).toHaveLength(0);
    await waitFor(() => {
      expect(sessionStorage.getItem("native_notification_seen_v1")).toContain(
        "notification:existing",
      );
    });

    act(() => {
      queryClient.setQueryData(["native-bridge", "notifications"], {
        items: [
          { id: "existing", message: "Already present" },
          { id: "new", message: "A new proactive update" },
        ],
        total: 2,
        offset: 0,
        limit: 6,
      });
    });

    await waitFor(() => expect(mocks.notificationsShown).toHaveLength(1));
    expect(mocks.notificationsShown[0]).toMatchObject({
      title: "Pulse update",
      options: {
        body: "A new proactive update",
        tag: "notification:new",
      },
    });

    act(() => {
      queryClient.setQueryData(["native-bridge", "notifications"], {
        items: [
          { id: "existing", message: "Already present" },
          { id: "new", message: "A new proactive update" },
        ],
        total: 2,
        offset: 0,
        limit: 6,
      });
    });
    await Promise.resolve();
    expect(mocks.notificationsShown).toHaveLength(1);
  });

  it("alerts once when an agent run gains multiple pending approvals", async () => {
    mocks.getWebPushConfig.mockResolvedValue({
      enabled: false,
      public_key: null,
      active_subscription_count: 0,
    });
    mocks.getAgentRuns.mockResolvedValue({
      items: [{ id: "run-1", pending_approvals: 1, specialist: null }],
      total: 1,
      offset: 0,
      limit: 8,
    });
    const queryClient = createTestQueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <ProactiveNotificationBridge />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(mocks.getAgentRuns).toHaveBeenCalledOnce());
    await waitFor(() => {
      expect(sessionStorage.getItem("native_notification_seen_v1")).toContain("approval:run-1:1");
    });

    act(() => {
      queryClient.setQueryData(["native-bridge", "agent-runs"], {
        items: [{ id: "run-1", pending_approvals: 2, specialist: null }],
        total: 1,
        offset: 0,
        limit: 8,
      });
    });

    await waitFor(() => expect(mocks.notificationsShown).toHaveLength(1));
    expect(mocks.notificationsShown[0]).toMatchObject({
      title: "Approval needed",
      options: {
        body: "assistant run is waiting on 2 approvals.",
        tag: "approval:run-1:2",
      },
    });

    act(() => {
      queryClient.setQueryData(["native-bridge", "agent-runs"], {
        items: [
          { id: "run-1", pending_approvals: 2, specialist: null },
          { id: "run-2", pending_approvals: 1, specialist: "calendar" },
        ],
        total: 2,
        offset: 0,
        limit: 8,
      });
    });

    await waitFor(() => expect(mocks.notificationsShown).toHaveLength(2));
    expect(mocks.notificationsShown[1]).toMatchObject({
      title: "Approval needed",
      options: {
        body: "calendar run is waiting on 1 approval.",
        tag: "approval:run-2:1",
      },
    });
  });

  it("recovers from invalid seen-state JSON and ignores persistence failures", async () => {
    sessionStorage.setItem("native_notification_seen_v1", "{invalid");
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("storage disabled");
    });
    mocks.getWebPushConfig.mockResolvedValue({
      enabled: false,
      public_key: null,
      active_subscription_count: 0,
    });
    mocks.getNotifications.mockResolvedValue({
      items: [{ id: "existing", message: "Already present" }],
      total: 1,
      offset: 0,
      limit: 6,
    });

    renderWithProviders(<ProactiveNotificationBridge />);

    await waitFor(() => expect(mocks.getNotifications).toHaveBeenCalledOnce());
    await waitFor(() => expect(setItem).toHaveBeenCalled());
    expect(mocks.notificationsShown).toHaveLength(0);
  });
});

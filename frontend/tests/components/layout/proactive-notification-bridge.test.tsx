import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import { renderWithProviders, waitFor } from "../../test-utils";
import { ProactiveNotificationBridge } from "@/components/layout/proactive-notification-bridge";

const mocks = vi.hoisted(() => ({
  getAgentRuns: vi.fn(),
  getNotifications: vi.fn(),
  getWebPushConfig: vi.fn(),
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
    class MockNotification {
      static permission: NotificationPermission = "granted";
      onclick: (() => void) | null = null;
      constructor(
        public title: string,
        public options?: NotificationOptions,
      ) {}
      close() {}
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
});

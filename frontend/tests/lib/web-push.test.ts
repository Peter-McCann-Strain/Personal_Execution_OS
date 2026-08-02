import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  disconnectCurrentBrowserPushSubscription,
  disconnectWebPushSubscription,
} from "@/lib/web-push";
import type { WebPushSubscription } from "@/types";

const mocks = vi.hoisted(() => ({
  deleteWebPushSubscription: vi.fn(),
  listWebPushSubscriptions: vi.fn(),
}));

vi.mock("@/api/notifications", () => ({
  deleteWebPushSubscription: mocks.deleteWebPushSubscription,
  listWebPushSubscriptions: mocks.listWebPushSubscriptions,
}));

const subscription: WebPushSubscription = {
  id: "subscription-1",
  status: "active",
  endpoint_preview: "https://push.example/subscription",
  endpoint_host: "push.example",
  expiration_time: null,
  user_agent: null,
  failure_count: 0,
  last_seen_at: null,
  last_success_at: null,
  last_failure_at: null,
  last_error: null,
  created_at: "2026-07-31T00:00:00Z",
  updated_at: "2026-07-31T00:00:00Z",
};

describe("disconnectWebPushSubscription", () => {
  const originalServiceWorker = navigator.serviceWorker;
  const originalPushManager = (window as Window & { PushManager?: unknown }).PushManager;
  const unsubscribe = vi.fn();

  beforeEach(() => {
    mocks.deleteWebPushSubscription.mockReset().mockResolvedValue(undefined);
    mocks.listWebPushSubscriptions.mockReset().mockResolvedValue([subscription]);
    unsubscribe.mockReset().mockResolvedValue(true);
    Object.defineProperty(window, "PushManager", {
      value: class PushManager {},
      configurable: true,
    });
    Object.defineProperty(navigator, "serviceWorker", {
      value: {
        ready: Promise.resolve({
          pushManager: {
            getSubscription: vi.fn().mockResolvedValue({
              endpoint: subscription.endpoint_preview,
              unsubscribe,
            }),
          },
        }),
      },
      configurable: true,
    });
  });

  afterEach(() => {
    Object.defineProperty(navigator, "serviceWorker", {
      value: originalServiceWorker,
      configurable: true,
    });
    Object.defineProperty(window, "PushManager", {
      value: originalPushManager,
      configurable: true,
    });
  });

  it("revokes both the server record and the matching browser subscription", async () => {
    await disconnectWebPushSubscription(subscription);

    expect(mocks.deleteWebPushSubscription).toHaveBeenCalledWith("subscription-1");
    expect(unsubscribe).toHaveBeenCalledOnce();
  });

  it("still removes the server record when the listed subscription belongs to another browser", async () => {
    const remoteSubscription = {
      ...subscription,
      id: "subscription-2",
      endpoint_preview: "https://another.example/subscription",
    };

    await disconnectWebPushSubscription(remoteSubscription);

    expect(mocks.deleteWebPushSubscription).toHaveBeenCalledWith("subscription-2");
    expect(unsubscribe).not.toHaveBeenCalled();
  });

  it("attempts server deletion even when browser revocation fails", async () => {
    unsubscribe.mockRejectedValue(new Error("browser rejected unsubscribe"));

    await expect(disconnectWebPushSubscription(subscription)).rejects.toThrow(
      "could not be fully disconnected",
    );
    expect(mocks.deleteWebPushSubscription).toHaveBeenCalledWith("subscription-1");
    expect(unsubscribe).toHaveBeenCalledOnce();
  });

  it("aggregates a server deletion failure after browser cleanup succeeds", async () => {
    mocks.deleteWebPushSubscription.mockRejectedValue(new Error("server delete failed"));

    await expect(disconnectWebPushSubscription(subscription)).rejects.toThrow(
      "could not be fully disconnected",
    );
    expect(unsubscribe).toHaveBeenCalledOnce();
  });

  it("treats a false browser unsubscribe result as a failed disconnection", async () => {
    unsubscribe.mockResolvedValue(false);

    await expect(disconnectWebPushSubscription(subscription)).rejects.toThrow(
      "could not be fully disconnected",
    );
    expect(mocks.deleteWebPushSubscription).toHaveBeenCalledWith("subscription-1");
  });

  it("removes the server record when browser push APIs are unavailable", async () => {
    Reflect.deleteProperty(window, "PushManager");

    await disconnectWebPushSubscription(subscription);

    expect(mocks.deleteWebPushSubscription).toHaveBeenCalledWith("subscription-1");
    expect(unsubscribe).not.toHaveBeenCalled();
  });

  it("matches long browser endpoints using the privacy-preserving preview", async () => {
    const endpoint = `https://push.example/${"a".repeat(60)}/subscription`;
    const longSubscription = {
      ...subscription,
      endpoint_preview: `${endpoint.slice(0, 28)}...${endpoint.slice(-10)}`,
    };
    Object.defineProperty(navigator, "serviceWorker", {
      value: {
        ready: Promise.resolve({
          pushManager: {
            getSubscription: vi.fn().mockResolvedValue({
              endpoint,
              unsubscribe,
            }),
          },
        }),
      },
      configurable: true,
    });

    await disconnectWebPushSubscription(longSubscription);

    expect(unsubscribe).toHaveBeenCalledOnce();
  });

  it("disconnects the current browser subscription and its matching server record", async () => {
    await disconnectCurrentBrowserPushSubscription();

    expect(unsubscribe).toHaveBeenCalledOnce();
    expect(mocks.deleteWebPushSubscription).toHaveBeenCalledWith("subscription-1");
  });

  it("still revokes the browser subscription when the authenticated server lookup fails", async () => {
    mocks.listWebPushSubscriptions.mockRejectedValue(new Error("session expired"));

    await expect(disconnectCurrentBrowserPushSubscription()).rejects.toThrow(
      "current browser push subscription was not fully removed",
    );
    expect(unsubscribe).toHaveBeenCalledOnce();
    expect(mocks.deleteWebPushSubscription).not.toHaveBeenCalled();
  });

  it("returns cleanly when this browser has no push subscription", async () => {
    Object.defineProperty(navigator, "serviceWorker", {
      value: {
        ready: Promise.resolve({
          pushManager: {
            getSubscription: vi.fn().mockResolvedValue(null),
          },
        }),
      },
      configurable: true,
    });

    await disconnectCurrentBrowserPushSubscription();

    expect(mocks.listWebPushSubscriptions).not.toHaveBeenCalled();
    expect(mocks.deleteWebPushSubscription).not.toHaveBeenCalled();
  });

  it("reports a false browser revocation result after removing the server record", async () => {
    unsubscribe.mockResolvedValue(false);

    await expect(disconnectCurrentBrowserPushSubscription()).rejects.toThrow(
      "current browser push subscription was not fully removed",
    );
    expect(mocks.deleteWebPushSubscription).toHaveBeenCalledWith("subscription-1");
  });

  it("succeeds without server deletion when no listed record matches this browser", async () => {
    mocks.listWebPushSubscriptions.mockResolvedValue([
      {
        ...subscription,
        id: "other-browser",
        endpoint_preview: "https://push.example/other",
      },
    ]);

    await disconnectCurrentBrowserPushSubscription();

    expect(unsubscribe).toHaveBeenCalledOnce();
    expect(mocks.deleteWebPushSubscription).not.toHaveBeenCalled();
  });

  it("aggregates failure when matching server-record deletion fails", async () => {
    mocks.deleteWebPushSubscription.mockRejectedValue(new Error("delete failed"));

    await expect(disconnectCurrentBrowserPushSubscription()).rejects.toThrow(
      "current browser push subscription was not fully removed",
    );
    expect(unsubscribe).toHaveBeenCalledOnce();
  });
});

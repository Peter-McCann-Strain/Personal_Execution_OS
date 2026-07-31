import { deleteWebPushSubscription, listWebPushSubscriptions } from "@/api/notifications";
import type { WebPushSubscription } from "@/types";

function endpointPreview(endpoint: string): string {
  const trimmed = endpoint.trim();
  if (trimmed.length <= 42) {
    return trimmed;
  }
  return `${trimmed.slice(0, 28)}...${trimmed.slice(-10)}`;
}

async function unsubscribeMatchingBrowserSubscription(
  serverSubscription: WebPushSubscription,
): Promise<void> {
  if (
    typeof navigator === "undefined" ||
    !("serviceWorker" in navigator) ||
    typeof window === "undefined" ||
    !("PushManager" in window)
  ) {
    return;
  }

  const registration = await navigator.serviceWorker.ready;
  const browserSubscription = await registration.pushManager.getSubscription();
  if (
    browserSubscription &&
    endpointPreview(browserSubscription.endpoint) === serverSubscription.endpoint_preview
  ) {
    const revoked = await browserSubscription.unsubscribe();
    if (!revoked) {
      throw new Error("The browser did not revoke its push subscription.");
    }
  }
}

async function getCurrentBrowserSubscription(): Promise<PushSubscription | null> {
  if (
    typeof navigator === "undefined" ||
    !("serviceWorker" in navigator) ||
    typeof window === "undefined" ||
    !("PushManager" in window)
  ) {
    return null;
  }
  const registration = await navigator.serviceWorker.ready;
  return registration.pushManager.getSubscription();
}

export async function disconnectWebPushSubscription(
  subscription: WebPushSubscription,
): Promise<void> {
  const results = await Promise.allSettled([
    deleteWebPushSubscription(subscription.id),
    unsubscribeMatchingBrowserSubscription(subscription),
  ]);
  const failures = results
    .filter((result): result is PromiseRejectedResult => result.status === "rejected")
    .map((result) => result.reason);

  if (failures.length > 0) {
    throw new AggregateError(failures, "The push subscription could not be fully disconnected.");
  }
}

export async function disconnectCurrentBrowserPushSubscription(): Promise<void> {
  const browserSubscription = await getCurrentBrowserSubscription();
  if (!browserSubscription) {
    return;
  }

  // Start browser revocation and server lookup together. A failed or expired
  // server session must never prevent the browser-side subscription from being
  // revoked.
  const [browserResult, listResult] = await Promise.allSettled([
    browserSubscription.unsubscribe(),
    listWebPushSubscriptions(),
  ]);
  const failures: unknown[] = [];

  if (browserResult.status === "rejected") {
    failures.push(browserResult.reason);
  } else if (browserResult.value !== true) {
    failures.push(new Error("The browser did not revoke its push subscription."));
  }

  if (listResult.status === "rejected") {
    failures.push(listResult.reason);
  } else {
    const matchingServerSubscription = listResult.value.find(
      (subscription) =>
        subscription.endpoint_preview === endpointPreview(browserSubscription.endpoint),
    );
    if (matchingServerSubscription) {
      try {
        await deleteWebPushSubscription(matchingServerSubscription.id);
      } catch (error) {
        failures.push(error);
      }
    }
  }

  if (failures.length > 0) {
    throw new AggregateError(
      failures,
      "The current browser push subscription was not fully removed.",
    );
  }
}

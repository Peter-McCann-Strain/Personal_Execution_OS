import { api, apiPath, getWithQuery } from "./client";
import { API_PATHS } from "./generated/paths";
import type {
  Notification,
  PaginatedResponse,
  Priority,
  NotificationCategory,
  WebPushConfig,
  WebPushSubscription,
} from "@/types";

// ─── Query Parameters ───────────────────────────────────────
export interface NotificationQueryParams {
  limit?: number;
  offset?: number;
  priority?: Priority[];
  category?: NotificationCategory;
  status?: "unread" | "read" | "dismissed";
  group_by?: "priority" | "category";
}

// ─── Fetch Notifications ────────────────────────────────────
export function getNotifications(
  params: NotificationQueryParams = {},
): Promise<PaginatedResponse<Notification>> {
  return getWithQuery<PaginatedResponse<Notification>, NotificationQueryParams>(
    apiPath(API_PATHS.apiNotifications),
    params,
  );
}

// ─── Dismiss Single Notification ────────────────────────────
export function dismissNotification(id: string): Promise<void> {
  return api.patch<void>(
    apiPath(API_PATHS.apiNotificationsByNotificationIdDismiss, {
      notification_id: id,
    }),
  );
}

// ─── Dismiss All Notifications ──────────────────────────────
export function dismissAllNotifications(): Promise<void> {
  return api.patch<void>(apiPath(API_PATHS.apiNotificationsDismissAll));
}

// ─── Mark All Read ──────────────────────────────────────────
export function markAllRead(): Promise<void> {
  return api.patch<void>(apiPath(API_PATHS.apiNotificationsMarkAllRead));
}

// ─── Unread Count ───────────────────────────────────────────
export interface UnreadCount {
  total: number;
  hasP0: boolean;
  hasP1: boolean;
}

export function getUnreadCount(): Promise<UnreadCount> {
  return api.get<UnreadCount>(apiPath(API_PATHS.apiNotificationsUnreadCount));
}

export interface RegisterWebPushSubscriptionData {
  endpoint: string;
  expiration_time?: number | null;
  keys: {
    auth: string;
    p256dh: string;
  };
  metadata?: Record<string, unknown>;
}

export function getWebPushConfig(): Promise<WebPushConfig> {
  return api.get<WebPushConfig>(apiPath(API_PATHS.apiNotificationsPushConfig));
}

export function listWebPushSubscriptions(): Promise<WebPushSubscription[]> {
  return api.get<WebPushSubscription[]>(apiPath(API_PATHS.apiNotificationsPushSubscriptions));
}

export function registerWebPushSubscription(
  data: RegisterWebPushSubscriptionData,
): Promise<WebPushSubscription> {
  return api.post<WebPushSubscription>(apiPath(API_PATHS.apiNotificationsPushSubscriptions), data);
}

export function deleteWebPushSubscription(subscriptionId: string): Promise<void> {
  return api.delete<void>(
    apiPath(API_PATHS.apiNotificationsPushSubscriptionsBySubscriptionId, {
      subscription_id: subscriptionId,
    }),
  );
}

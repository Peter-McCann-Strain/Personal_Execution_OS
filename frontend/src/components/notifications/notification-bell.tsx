import { useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router";
import { Bell, X } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { cn, formatRelativeTime } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { PriorityBadge } from "@/components/ui/badge";
import {
  getNotifications,
  getUnreadCount,
  dismissNotification,
  markAllRead,
} from "@/api/notifications";
import { categoryIconMap } from "./notification-card.config";
import type { Notification } from "@/types";

// ─── NotificationBell Component ─────────────────────────────

function NotificationBell() {
  const [isOpen, setIsOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  // Fetch unread count
  const { data: unreadData } = useQuery({
    queryKey: ["notifications", "unread-count"],
    queryFn: getUnreadCount,
    refetchInterval: 30_000,
  });

  // Fetch latest notifications for dropdown
  const { data: notificationsData } = useQuery({
    queryKey: ["notifications", "bell"],
    queryFn: () => getNotifications({ limit: 5, status: "unread" }),
    enabled: isOpen,
  });

  const notifications = notificationsData?.items ?? [];
  const unreadCount = unreadData?.total ?? 0;
  const hasP0 = unreadData?.hasP0 ?? false;
  const hasP1 = unreadData?.hasP1 ?? false;

  // Dismiss mutation
  const dismissMutation = useMutation({
    mutationFn: dismissNotification,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
  });

  // Mark all read mutation
  const markAllReadMutation = useMutation({
    mutationFn: markAllRead,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
  });

  // Close on outside click or Escape key
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (
        panelRef.current &&
        !panelRef.current.contains(e.target as Node) &&
        buttonRef.current &&
        !buttonRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false);
      }
    }
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setIsOpen(false);
      }
    }
    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
      document.addEventListener("keydown", handleKeyDown);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  return (
    <div className="relative">
      {/* Bell Button */}
      <button
        ref={buttonRef}
        onClick={() => setIsOpen((v) => !v)}
        className={cn(
          "relative flex h-9 w-9 items-center justify-center rounded-[var(--radius-md)] text-[var(--color-fg-tertiary)] hover:bg-[var(--color-bg-overlay)] hover:text-[var(--color-fg-primary)] transition-colors",
          (hasP0 || hasP1) && "text-[var(--color-fg-primary)]",
        )}
        aria-label="Notifications"
        aria-expanded={isOpen}
        aria-haspopup="true"
      >
        <Bell className="h-4 w-4" />

        {/* Unread count badge */}
        {unreadCount > 0 && (
          <span
            className={cn(
              "absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px] font-bold text-white",
              hasP0
                ? "bg-[var(--color-error-500)] animate-pulse"
                : hasP1
                  ? "bg-[var(--color-warning-500)]"
                  : "bg-[var(--color-info-500)]",
            )}
          >
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        )}
      </button>

      {/* Dropdown Panel */}
      {isOpen && (
        <div
          ref={panelRef}
          className="absolute right-0 top-full mt-2 z-50 w-96 rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] shadow-lg"
        >
          {/* Header */}
          <div className="flex items-center justify-between border-b border-[var(--color-border-subtle)] px-4 py-3">
            <h3 className="text-sm font-semibold text-[var(--color-fg-primary)]">Notifications</h3>
            {unreadCount > 0 && (
              <span className="text-xs text-[var(--color-fg-tertiary)]">{unreadCount} unread</span>
            )}
          </div>

          {/* Notification List */}
          <div className="max-h-[380px] overflow-y-auto">
            {notifications.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-8 px-4">
                <Bell className="h-8 w-8 text-[var(--color-fg-disabled)] mb-2" />
                <p className="text-sm text-[var(--color-fg-tertiary)]">No new notifications</p>
              </div>
            ) : (
              notifications.map((notification) => (
                <NotificationDropdownItem
                  key={notification.id}
                  notification={notification}
                  onDismiss={(id) => dismissMutation.mutate(id)}
                />
              ))
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between border-t border-[var(--color-border-subtle)] px-4 py-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => markAllReadMutation.mutate()}
              disabled={unreadCount === 0}
              className="text-xs"
            >
              Mark All Read
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setIsOpen(false);
                navigate("/notifications");
              }}
              className="text-xs text-[var(--color-info-500)]"
            >
              View All
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Dropdown Item ──────────────────────────────────────────

interface NotificationDropdownItemProps {
  notification: Notification;
  onDismiss: (id: string) => void;
}

function NotificationDropdownItem({ notification, onDismiss }: NotificationDropdownItemProps) {
  const CategoryIcon = categoryIconMap[notification.category];

  return (
    <div className="group flex items-start gap-3 px-4 py-3 hover:bg-[var(--color-bg-overlay)] transition-colors">
      {/* Priority + Category */}
      <div className="flex items-center gap-1.5 shrink-0 pt-0.5">
        <PriorityBadge priority={notification.priority} size="sm" />
        <CategoryIcon className="h-4 w-4 text-[var(--color-fg-tertiary)]" />
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <p
          className={cn(
            "text-sm leading-snug line-clamp-2",
            !notification.dismissed
              ? "font-medium text-[var(--color-fg-primary)]"
              : "text-[var(--color-fg-secondary)]",
          )}
        >
          {notification.message}
        </p>
        <span className="text-xs text-[var(--color-fg-tertiary)] mt-0.5 block">
          {formatRelativeTime(notification.created_at)}
        </span>
      </div>

      {/* Dismiss */}
      <button
        onClick={(e) => {
          e.stopPropagation();
          onDismiss(notification.id);
        }}
        className="opacity-0 group-hover:opacity-100 transition-opacity shrink-0 p-1 rounded-[var(--radius-sm)] text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-primary)] hover:bg-[var(--color-bg-wash)]"
        aria-label="Dismiss notification"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

export { NotificationBell };

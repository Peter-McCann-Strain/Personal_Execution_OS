import { memo } from "react";
import { X, ExternalLink } from "lucide-react";
import { cn, formatRelativeTime } from "@/lib/utils";
import { PriorityBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { categoryIconMap, categoryLabelMap } from "./notification-card.config";
import type { Notification, NotificationCategory, Priority } from "@/types";

// ─── Priority Border Colors ─────────────────────────────────

const priorityBorderMap: Record<Priority, string> = {
  P0: "border-l-[var(--color-error-500)]",
  P1: "border-l-[var(--color-warning-500)]",
  P2: "border-l-[var(--color-info-500)]",
  P3: "border-l-[var(--color-border-default)]",
};

// ─── Action Button Labels ───────────────────────────────────

const categoryActionMap: Record<NotificationCategory, { label: string; path: string } | null> = {
  deadline: { label: "Check Calendar", path: "/calendar" },
  commitment: { label: "Review Commitments", path: "/goals" },
  relationship: { label: "View Contact", path: "/contacts" },
  system: { label: "View Health", path: "/monitoring" },
  digest: null,
  proactive: { label: "Open Pulse", path: "/pulse" },
  tutorial: { label: "Open Tutorials", path: "/tutorials" },
};

// ─── NotificationCard Component ─────────────────────────────

interface NotificationCardProps {
  notification: Notification;
  onDismiss: (id: string) => void;
  onAction?: (path: string) => void;
}

const NotificationCard = memo(function NotificationCard({
  notification,
  onDismiss,
  onAction,
}: NotificationCardProps) {
  const CategoryIcon = categoryIconMap[notification.category];
  const action = categoryActionMap[notification.category];
  const isUnread = !notification.dismissed;

  return (
    <Card
      padding="none"
      className={cn(
        "group relative border-l-4 transition-all duration-200",
        "hover:border-[var(--color-border-strong)] hover:shadow-sm",
        priorityBorderMap[notification.priority],
        isUnread ? "bg-[var(--color-bg-elevated)]" : "bg-[var(--color-bg-surface)]",
        notification.priority === "P0" && isUnread && "animate-pulse-subtle",
      )}
    >
      <div className="p-4">
        {/* Header row */}
        <div className="flex items-center gap-2 mb-2">
          <PriorityBadge priority={notification.priority} size="sm" />
          <CategoryIcon className="h-4 w-4 text-[var(--color-fg-tertiary)]" />
          <span className="text-xs font-semibold uppercase tracking-wider text-[var(--color-fg-tertiary)]">
            {categoryLabelMap[notification.category]}
          </span>
          <span className="ml-auto text-xs text-[var(--color-fg-tertiary)]">
            {formatRelativeTime(notification.created_at)}
          </span>
        </div>

        {/* Message */}
        <p
          className={cn(
            "text-sm leading-relaxed",
            isUnread
              ? "text-[var(--color-fg-primary)] font-medium"
              : "text-[var(--color-fg-secondary)]",
          )}
        >
          {notification.message}
        </p>

        {/* Actions */}
        <div className="flex items-center justify-end gap-2 mt-3">
          {action && onAction && (
            <Button variant="outline" size="sm" onClick={() => onAction(action.path)}>
              <ExternalLink className="h-3.5 w-3.5" />
              {action.label}
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onDismiss(notification.id)}
            className="opacity-0 group-hover:opacity-100 transition-opacity text-[var(--color-fg-tertiary)]"
          >
            <X className="h-3.5 w-3.5" />
            Dismiss
          </Button>
        </div>
      </div>
    </Card>
  );
});

export { NotificationCard };
export type { NotificationCardProps };

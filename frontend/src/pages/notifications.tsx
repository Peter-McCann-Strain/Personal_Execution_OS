import { useState, useCallback } from "react";
import { useNavigate } from "react-router";
import { Bell, Filter, Trash2, BellOff } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { NotificationCard } from "@/components/notifications/notification-card";
import { Skeleton } from "@/components/ui/skeleton";
import { PageError } from "@/components/ui/page-error";
import { PageHeader } from "@/components/ui/page-header";
import { PageTransition } from "@/components/ui/page-transition";
import { EmptyState } from "@/components/ui/empty-state";
import {
  getNotifications,
  dismissNotification,
  dismissAllNotifications,
  type NotificationQueryParams,
} from "@/api/notifications";
import type { Priority, NotificationCategory, Notification } from "@/types";

// ─── Priority Filter Options ────────────────────────────────

const priorities: Priority[] = ["P0", "P1", "P2", "P3"];

const categories: { value: NotificationCategory | "all"; label: string }[] = [
  { value: "all", label: "All Categories" },
  { value: "deadline", label: "Deadline" },
  { value: "commitment", label: "Commitment" },
  { value: "relationship", label: "Relationship" },
  { value: "system", label: "System" },
  { value: "digest", label: "Digest" },
  { value: "proactive", label: "Proactive" },
  { value: "tutorial", label: "Tutorial" },
];

const statusOptions: { value: "all" | "unread" | "read"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "unread", label: "Unread" },
  { value: "read", label: "Read" },
];

// ─── Priority Label Map ─────────────────────────────────────

const priorityLabels: Record<Priority, string> = {
  P0: "Critical",
  P1: "Important",
  P2: "Normal",
  P3: "Low",
};

// ─── NotificationsPage Component ────────────────────────────

function NotificationsPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  // Filter state
  const [selectedPriorities, setSelectedPriorities] = useState<Priority[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<NotificationCategory | "all">("all");
  const [selectedStatus, setSelectedStatus] = useState<"all" | "unread" | "read">("all");
  const [groupByPriority, setGroupByPriority] = useState(false);

  // Build query params
  const queryParams: NotificationQueryParams = {
    limit: 50,
    priority: selectedPriorities.length > 0 ? selectedPriorities : undefined,
    category: selectedCategory !== "all" ? selectedCategory : undefined,
    status: selectedStatus !== "all" ? selectedStatus : undefined,
  };

  // Fetch notifications
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["notifications", "page", queryParams],
    queryFn: () => getNotifications(queryParams),
  });

  const notifications = data?.items ?? [];

  // Dismiss single
  const dismissMutation = useMutation({
    mutationFn: dismissNotification,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
      toast.success("Notification dismissed");
    },
  });

  // Dismiss all
  const dismissAllMutation = useMutation({
    mutationFn: dismissAllNotifications,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
      toast.success("All notifications dismissed");
    },
  });

  // Priority filter toggle
  const togglePriority = useCallback((p: Priority) => {
    setSelectedPriorities((prev) =>
      prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p],
    );
  }, []);

  // Group by priority
  const groupedNotifications = groupByPriority ? groupNotificationsByPriority(notifications) : null;

  return (
    <PageTransition>
      <div className="flex flex-col gap-6 p-6 max-w-4xl mx-auto">
        {/* Header */}
        <PageHeader
          title="Notifications"
          subtitle="Alerts and reminders"
          icon={Bell}
          agentColor="notification"
        >
          {data && (
            <span className="text-sm text-[var(--color-fg-tertiary)]">({data.total} total)</span>
          )}
          <Button
            variant="destructive"
            size="sm"
            onClick={() => dismissAllMutation.mutate()}
            loading={dismissAllMutation.isPending}
            disabled={notifications.length === 0}
          >
            <Trash2 className="h-3.5 w-3.5" />
            Dismiss All
          </Button>
        </PageHeader>

        {/* Filter Bar */}
        <div className="flex flex-col gap-3 rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-4">
          <div className="flex items-center gap-2 text-sm text-[var(--color-fg-secondary)]">
            <Filter className="h-4 w-4" />
            <span className="font-medium">Filters</span>
          </div>

          {/* Priority checkboxes */}
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-xs font-medium text-[var(--color-fg-tertiary)] uppercase tracking-wider">
              Priority
            </span>
            {priorities.map((p) => (
              <label key={p} className="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={selectedPriorities.includes(p)}
                  onChange={() => togglePriority(p)}
                  className="h-3.5 w-3.5 rounded border-[var(--color-border-default)] bg-[var(--color-bg-surface)] accent-[var(--color-info-500)]"
                />
                <span className="text-xs text-[var(--color-fg-secondary)]">{p}</span>
              </label>
            ))}
          </div>

          {/* Category & Status */}
          <div className="flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-[var(--color-fg-tertiary)] uppercase tracking-wider">
                Category
              </span>
              <select
                aria-label="Notification category filter"
                value={selectedCategory}
                onChange={(e) =>
                  setSelectedCategory(e.target.value as NotificationCategory | "all")
                }
                className="h-8 rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] px-2 text-xs text-[var(--color-fg-primary)]"
              >
                {categories.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </select>
            </div>

            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-[var(--color-fg-tertiary)] uppercase tracking-wider">
                Status
              </span>
              <SegmentedControl
                value={selectedStatus}
                onChange={setSelectedStatus}
                options={statusOptions}
                label="Notification status filter"
              />
            </div>

            <div className="flex items-center gap-2 ml-auto">
              <span className="text-xs font-medium text-[var(--color-fg-tertiary)] uppercase tracking-wider">
                Group
              </span>
              <button
                onClick={() => setGroupByPriority((v) => !v)}
                aria-pressed={groupByPriority}
                aria-label="Group notifications by priority"
                className={cn(
                  "h-7 px-2.5 rounded-[var(--radius-md)] border text-xs font-medium transition-colors",
                  groupByPriority
                    ? "border-[var(--color-info-500)] bg-[var(--color-info-500)] text-[var(--color-fg-on-accent)]"
                    : "border-[var(--color-border-default)] text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-secondary)]",
                )}
              >
                By Priority
              </button>
            </div>
          </div>
        </div>

        {/* Notification List */}
        {error ? (
          <PageError
            message={error.message ?? "Failed to load notifications"}
            onRetry={() => refetch()}
            context="your notifications"
            icon={Bell}
          />
        ) : isLoading ? (
          <div className="flex flex-col gap-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-28 w-full" />
            ))}
          </div>
        ) : notifications.length === 0 ? (
          <EmptyState icon={BellOff} title="No notifications match your filters" />
        ) : groupByPriority && groupedNotifications ? (
          <div className="flex flex-col gap-6">
            {priorities.map((p) => {
              const group = groupedNotifications[p];
              if (!group || group.length === 0) return null;
              return (
                <div key={p} className="flex flex-col gap-3">
                  <div className="flex items-center gap-2">
                    <div
                      className={cn(
                        "h-px flex-1",
                        p === "P0"
                          ? "bg-[var(--color-error-500)]"
                          : p === "P1"
                            ? "bg-[var(--color-warning-500)]"
                            : p === "P2"
                              ? "bg-[var(--color-info-500)]"
                              : "bg-[var(--color-border-default)]",
                      )}
                    />
                    <span
                      className={cn(
                        "text-xs font-semibold uppercase tracking-wider",
                        p === "P0"
                          ? "text-[var(--color-error-900)]"
                          : p === "P1"
                            ? "text-[var(--color-warning-900)]"
                            : p === "P2"
                              ? "text-[var(--color-info-900)]"
                              : "text-[var(--color-fg-tertiary)]",
                      )}
                    >
                      {p} {priorityLabels[p]} ({group.length})
                    </span>
                    <div
                      className={cn(
                        "h-px flex-1",
                        p === "P0"
                          ? "bg-[var(--color-error-500)]"
                          : p === "P1"
                            ? "bg-[var(--color-warning-500)]"
                            : p === "P2"
                              ? "bg-[var(--color-info-500)]"
                              : "bg-[var(--color-border-default)]",
                      )}
                    />
                  </div>
                  {group.map((n) => (
                    <NotificationCard
                      key={n.id}
                      notification={n}
                      onDismiss={(id) => dismissMutation.mutate(id)}
                      onAction={(path) => navigate(path)}
                    />
                  ))}
                </div>
              );
            })}
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {notifications.map((n) => (
              <NotificationCard
                key={n.id}
                notification={n}
                onDismiss={(id) => dismissMutation.mutate(id)}
                onAction={(path) => navigate(path)}
              />
            ))}
          </div>
        )}
      </div>
    </PageTransition>
  );
}

// ─── Helpers ────────────────────────────────────────────────

function groupNotificationsByPriority(
  notifications: Notification[],
): Record<Priority, Notification[]> {
  const groups: Record<Priority, Notification[]> = {
    P0: [],
    P1: [],
    P2: [],
    P3: [],
  };
  for (const n of notifications) {
    groups[n.priority].push(n);
  }
  return groups;
}

export { NotificationsPage };

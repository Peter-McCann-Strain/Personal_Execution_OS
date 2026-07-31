import { useQuery } from "@tanstack/react-query";
import { Calendar, ExternalLink, ChevronRight, Sun, Moon, Sunset, Coffee } from "lucide-react";
import { format } from "date-fns";
import { getMorningBriefing } from "@/api/dashboard";
import { truncate } from "@/lib/utils";
import { PriorityBadge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import type { CalendarEvent, Notification } from "@/types";

function getGreetingIcon() {
  const hour = new Date().getHours();
  if (hour >= 6 && hour < 12) return <Sun className="h-5 w-5 text-[var(--color-warning-500)]" />;
  if (hour >= 12 && hour < 17)
    return <Sunset className="h-5 w-5 text-[var(--color-agent-diary)]" />;
  if (hour >= 17 && hour < 21) return <Moon className="h-5 w-5 text-[var(--color-info-500)]" />;
  return <Coffee className="h-5 w-5 text-[var(--color-fg-secondary)]" />;
}

function getGreetingText(): string {
  const hour = new Date().getHours();
  if (hour >= 6 && hour < 12) return "Good morning";
  if (hour >= 12 && hour < 17) return "Good afternoon";
  if (hour >= 17 && hour < 21) return "Good evening";
  return "Working late";
}

function ScheduleItem({ event }: { event: CalendarEvent }) {
  const startTime = format(new Date(event.start), "HH:mm");
  const endTime = new Date(event.end);
  const startDate = new Date(event.start);
  const durationMin = Math.round((endTime.getTime() - startDate.getTime()) / 60000);
  const durationLabel = durationMin >= 60 ? `${Math.round(durationMin / 60)}h` : `${durationMin}m`;

  return (
    <div className="flex items-center gap-3 rounded-[var(--radius-md)] px-2 py-1.5 hover:bg-[var(--color-bg-elevated)] transition-colors">
      <span className="text-xs font-mono tabular-nums text-[var(--color-fg-secondary)] w-10 shrink-0">
        {startTime}
      </span>
      <span className="text-sm text-[var(--color-fg-primary)] truncate flex-1">
        {truncate(event.summary, 30)}
      </span>
      <span className="text-xs text-[var(--color-fg-tertiary)] shrink-0">({durationLabel})</span>
      <Calendar className="h-3 w-3 text-[var(--color-fg-tertiary)] shrink-0" />
    </div>
  );
}

function NotificationItem({ notification }: { notification: Notification }) {
  return (
    <div className="flex items-start gap-2 px-2 py-1.5">
      <PriorityBadge priority={notification.priority} size="sm" className="shrink-0 mt-0.5" />
      <span className="text-sm text-[var(--color-fg-primary)] line-clamp-1">
        {truncate(notification.message, 60)}
      </span>
    </div>
  );
}

interface ContentItem {
  title: string;
  source: string;
  url: string;
  relevance: number;
}

function CuratedContentItem({ item }: { item: ContentItem }) {
  return (
    <a
      href={item.url}
      target="_blank"
      rel="noopener noreferrer"
      className="flex items-start gap-2 rounded-[var(--radius-md)] px-2 py-1.5 hover:bg-[var(--color-bg-elevated)] transition-colors group"
    >
      <span className="text-xs font-medium text-[var(--color-info-500)] shrink-0 tabular-nums w-8">
        {Math.round(item.relevance * 100)}%
      </span>
      <div className="flex-1 min-w-0">
        <p className="text-sm text-[var(--color-fg-primary)] line-clamp-1 group-hover:text-[var(--color-info-500)] transition-colors">
          {truncate(item.title, 40)}
        </p>
        <p className="text-xs text-[var(--color-fg-tertiary)]">{item.source}</p>
      </div>
      <ExternalLink className="h-3 w-3 text-[var(--color-fg-tertiary)] shrink-0 mt-1 opacity-0 group-hover:opacity-100 transition-opacity" />
    </a>
  );
}

function parseCognitiveLoad(load: number | string): number | null {
  if (typeof load === "number" && !Number.isNaN(load)) return load;
  if (typeof load === "string") {
    const num = Number(load);
    if (!Number.isNaN(num)) return num;
    const map: Record<string, number> = {
      low: 3,
      moderate: 5,
      high: 7,
      critical: 9,
    };
    return map[load.toLowerCase()] ?? null;
  }
  return null;
}

function CognitiveLoadBar({ load }: { load: number | string }) {
  const parsed = parseCognitiveLoad(load);
  if (parsed == null) return null;
  const clamped = Math.min(10, Math.max(0, parsed));
  const pct = clamped * 10;
  const barColor =
    clamped <= 3
      ? "var(--color-success-500)"
      : clamped <= 6
        ? "var(--color-warning-500)"
        : "var(--color-error-500)";

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-[var(--color-fg-secondary)]">Cognitive Load:</span>
      <div className="h-2 w-24 rounded-[var(--radius-full)] bg-[var(--color-bg-overlay)] overflow-hidden">
        <div
          className="h-full rounded-[var(--radius-full)] transition-all duration-500"
          style={{ width: `${pct}%`, backgroundColor: barColor }}
        />
      </div>
      <span className="text-xs font-medium tabular-nums text-[var(--color-fg-primary)]">
        {clamped}/10
      </span>
    </div>
  );
}

export function MorningBriefing() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["morningBriefing"],
    queryFn: getMorningBriefing,
    staleTime: 60_000,
  });

  if (isLoading) return <MorningBriefingSkeleton />;

  if (isError || !data) {
    return (
      <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-6">
        <p className="text-sm text-[var(--color-fg-secondary)]">
          Unable to load briefing. Try refreshing the page.
        </p>
      </div>
    );
  }

  const greeting = data.greeting;
  const schedule = data.schedule.slice(0, 3);
  const notifications = data.notifications.filter(
    (n: Notification) => n.priority === "P0" || n.priority === "P1",
  );
  const content = data.content.slice(0, 3);
  const notices = data.notices ?? [];

  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)]">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[var(--color-border-subtle)] px-4 py-3">
        <h2 className="text-sm font-semibold text-[var(--color-fg-primary)]">Morning Briefing</h2>
        <a
          href="/briefing"
          className="inline-flex items-center gap-1 text-xs text-[var(--color-info-500)] hover:text-[var(--color-info-600)] transition-colors"
        >
          View Full <ChevronRight className="h-3 w-3" />
        </a>
      </div>

      {/* Content grid */}
      {notices.length > 0 && (
        <div className="border-b border-[var(--color-border-subtle)] px-4 py-3">
          <div className="flex flex-wrap gap-2">
            {notices.map((notice) => (
              <div
                key={`${notice.source}-${notice.status}-${notice.errorCategory ?? "n"}`}
                className="rounded-[var(--radius-full)] border border-[var(--color-border-default)] bg-[var(--color-bg-overlay)] px-2.5 py-1 text-[11px] text-[var(--color-fg-secondary)]"
                data-testid="briefing-notice"
                data-category={notice.errorCategory ?? undefined}
              >
                <span className="font-medium capitalize">{notice.source}:</span> {notice.message}
                {notice.actionable && notice.actionUrl ? (
                  <>
                    {" "}
                    <a
                      href={notice.actionUrl}
                      className="font-semibold underline"
                      data-testid="briefing-notice-reconnect"
                    >
                      Reconnect
                    </a>
                  </>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      )}
      <div className="grid grid-cols-1 md:grid-cols-2 divide-y md:divide-y-0 md:divide-x divide-[var(--color-border-subtle)]">
        {/* Left: Greeting + Schedule */}
        <div className="space-y-4 p-4">
          {/* Greeting */}
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              {getGreetingIcon()}
              <span className="text-base font-semibold text-[var(--color-fg-primary)]">
                {greeting?.greeting || getGreetingText()}
              </span>
            </div>
            <p className="text-xs text-[var(--color-fg-secondary)]">
              {greeting?.dateString || format(new Date(), "EEEE d MMMM yyyy")}
            </p>
            {greeting?.cognitiveLoad != null && <CognitiveLoadBar load={greeting.cognitiveLoad} />}
            {greeting?.summary && (
              <p className="text-xs italic text-[var(--color-fg-tertiary)]">
                &ldquo;{greeting.summary}&rdquo;
              </p>
            )}
          </div>

          {/* Schedule */}
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-[var(--color-fg-tertiary)] mb-1">
              Today&apos;s Schedule
            </p>
            {schedule.length > 0 ? (
              <div className="space-y-0.5">
                {schedule.map((event: CalendarEvent) => (
                  <ScheduleItem key={event.id} event={event} />
                ))}
              </div>
            ) : (
              <p className="text-xs text-[var(--color-fg-tertiary)] py-2">
                No events scheduled. A clear day for deep work.
              </p>
            )}
          </div>
        </div>

        {/* Right: Notifications + Content */}
        <div className="space-y-4 p-4">
          {/* Priority Notifications */}
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-[var(--color-fg-tertiary)] mb-1">
              Priority Notifications
            </p>
            {notifications.length > 0 ? (
              <div className="space-y-0.5">
                {notifications.slice(0, 4).map((n: Notification) => (
                  <NotificationItem key={n.id} notification={n} />
                ))}
              </div>
            ) : (
              <p className="text-xs text-[var(--color-fg-tertiary)] py-2">
                All clear. No urgent notifications.
              </p>
            )}
          </div>

          {/* Curated Content */}
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-[var(--color-fg-tertiary)] mb-1">
              Curated Content
            </p>
            {content.length > 0 ? (
              <div className="space-y-0.5">
                {content.map((item: ContentItem) => (
                  <CuratedContentItem key={item.url} item={item} />
                ))}
              </div>
            ) : (
              <p className="text-xs text-[var(--color-fg-tertiary)] py-2">
                No curated content available.
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function MorningBriefingSkeleton() {
  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)]">
      <div className="flex items-center justify-between border-b border-[var(--color-border-subtle)] px-4 py-3">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-3 w-16" />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 divide-y md:divide-y-0 md:divide-x divide-[var(--color-border-subtle)]">
        <div className="space-y-3 p-4">
          <Skeleton className="h-5 w-48" />
          <Skeleton className="h-3 w-36" />
          <div className="space-y-2 mt-4">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-3/4" />
          </div>
        </div>
        <div className="space-y-3 p-4">
          <div className="space-y-2">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-full" />
          </div>
          <div className="space-y-2 mt-4">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-4 w-5/6" />
          </div>
        </div>
      </div>
    </div>
  );
}

export { MorningBriefingSkeleton };

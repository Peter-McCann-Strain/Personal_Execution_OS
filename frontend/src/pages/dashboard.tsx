import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, LayoutDashboard, RefreshCw } from "lucide-react";
import { getDashboardStats, getRecentDiaryEntries } from "@/api/dashboard";
import { StatCard, StatCardSkeleton } from "@/components/dashboard/stat-card";
import { MorningBriefing } from "@/components/dashboard/morning-briefing";
import { TodayCockpit } from "@/components/dashboard/today-cockpit";
import { MoodChart } from "@/components/dashboard/mood-chart";
import { GoalProgress } from "@/components/dashboard/goal-progress";
import { RecentActivity } from "@/components/dashboard/recent-activity";
import { QuickActions } from "@/components/dashboard/quick-actions";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/ui/page-header";
import { PageTransition } from "@/components/ui/page-transition";
import { ParaBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatRelativeTime, truncate } from "@/lib/utils";
import type { Episode } from "@/types";

function RecentDiaryWidget() {
  const { data, isLoading } = useQuery({
    queryKey: ["recentDiary"],
    queryFn: () => getRecentDiaryEntries(3),
    staleTime: 30_000,
  });

  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)]">
      <div className="border-b border-[var(--color-border-subtle)] px-4 py-3">
        <h3 className="text-sm font-semibold text-[var(--color-fg-primary)]">Recent Diary</h3>
      </div>
      <div className="divide-y divide-[var(--color-border-subtle)]">
        {isLoading &&
          Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="p-4 space-y-2">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-3 w-3/4" />
            </div>
          ))}

        {data && data.length === 0 && (
          <div className="p-6 text-center">
            <p className="text-xs text-[var(--color-fg-tertiary)]">
              No diary entries yet. Start capturing your thoughts.
            </p>
          </div>
        )}

        {data &&
          data.map((entry: Episode) => (
            <div
              key={entry.id}
              className="px-4 py-3 hover:bg-[var(--color-bg-elevated)] transition-colors"
            >
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-[var(--color-fg-tertiary)]">
                  {formatRelativeTime(entry.created_at)}
                </span>
                {entry.para_category && <ParaBadge category={entry.para_category} size="sm" />}
              </div>
              <p className="text-sm text-[var(--color-fg-primary)] line-clamp-2">
                {entry.summary ? truncate(entry.summary, 80) : truncate(entry.content, 80)}
              </p>
              <div className="flex items-center gap-3 mt-1.5">
                {entry.mood_score != null && (
                  <span className="text-xs text-[var(--color-fg-secondary)]">
                    Mood: {entry.mood_score.toFixed(1)}
                  </span>
                )}
                {entry.energy_rating != null && (
                  <span className="text-xs text-[var(--color-fg-secondary)]">
                    Energy: {entry.energy_rating.toFixed(1)}
                  </span>
                )}
              </div>
              {entry.tags.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1.5">
                  {entry.tags.slice(0, 3).map((tag) => (
                    <span
                      key={tag}
                      className="text-[10px] px-1.5 py-0.5 rounded-[var(--radius-full)] bg-[var(--color-bg-overlay)] text-[var(--color-fg-secondary)]"
                    >
                      {tag}
                    </span>
                  ))}
                  {entry.tags.length > 3 && (
                    <span className="text-[10px] text-[var(--color-fg-tertiary)]">
                      +{entry.tags.length - 3}
                    </span>
                  )}
                </div>
              )}
            </div>
          ))}
      </div>
    </div>
  );
}

function DashboardPage() {
  const {
    data: stats,
    isLoading: statsLoading,
    error: statsError,
    refetch: refetchStats,
  } = useQuery({
    queryKey: ["dashboardStats"],
    queryFn: getDashboardStats,
    staleTime: 30_000,
  });

  const resolveEmptyText = (message: string | null | undefined, fallback: string) =>
    message || fallback;

  return (
    <PageTransition>
      <div className="mx-auto max-w-[1400px] space-y-6 p-6">
        {/* Page title */}
        <PageHeader
          title="Dashboard"
          subtitle="Your personal command centre"
          icon={LayoutDashboard}
        />

        {/* Row 1: Today cockpit */}
        <TodayCockpit />

        {/* Row 2: Stat cards */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {statsError ? (
            <div className="flex flex-col gap-3 rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-4 sm:col-span-2 sm:flex-row sm:items-center sm:justify-between xl:col-span-4">
              <div className="flex items-start gap-3">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--color-error-500)]/10">
                  <AlertTriangle className="h-4 w-4 text-[var(--color-error-500)]" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-[var(--color-fg-primary)]">
                    Dashboard stats unavailable
                  </h3>
                  <p className="mt-1 text-xs text-[var(--color-fg-tertiary)]">
                    {statsError.message || "The summary cards could not be loaded."}
                  </p>
                </div>
              </div>
              <Button variant="outline" size="sm" onClick={() => refetchStats()}>
                <RefreshCw className="h-3.5 w-3.5" />
                Retry
              </Button>
            </div>
          ) : statsLoading || !stats ? (
            Array.from({ length: 4 }).map((_, i) => <StatCardSkeleton key={i} />)
          ) : (
            <>
              <StatCard
                value={stats.mood.value}
                label="Today's Mood"
                trend={stats.mood.trend}
                sparkline={stats.mood.sparkline}
                subLabel={stats.mood.subLabel}
                agentColor="diary"
                emptyText={resolveEmptyText(stats.mood.message, "Log your first diary entry")}
                formatValue={(v) => v.toFixed(1)}
              />
              <StatCard
                value={stats.projects.value}
                label="Active Projects"
                trend={stats.projects.trend}
                sparkline={stats.projects.sparkline}
                subLabel={stats.projects.subLabel}
                agentColor="project"
                emptyText={resolveEmptyText(stats.projects.message, "Create your first project")}
              />
              <StatCard
                value={stats.emails.value}
                label="Unread Emails"
                trend={stats.emails.trend}
                sparkline={stats.emails.sparkline}
                subLabel={stats.emails.subLabel}
                agentColor="communications"
                emptyText={resolveEmptyText(stats.emails.message, "Inbox zero!")}
                status={stats.emails.status}
                errorCategory={stats.emails.errorCategory}
                actionable={stats.emails.actionable}
                actionUrl={stats.emails.actionUrl}
                errorMessage={stats.emails.message}
              />
              <StatCard
                value={stats.events.value}
                label="Events Today"
                trend={stats.events.trend}
                sparkline={stats.events.sparkline}
                subLabel={stats.events.subLabel}
                agentColor="tools"
                emptyText={resolveEmptyText(stats.events.message, "No events -- Free day!")}
                status={stats.events.status}
                errorCategory={stats.events.errorCategory}
                actionable={stats.events.actionable}
                actionUrl={stats.events.actionUrl}
                errorMessage={stats.events.message}
              />
            </>
          )}
        </div>

        {/* Row 3: Morning briefing */}
        <MorningBriefing />

        {/* Row 4: 2-column layout */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {/* Left column: Mood chart + Goal progress */}
          <div className="space-y-6">
            <MoodChart days={30} />
            <GoalProgress />
          </div>

          {/* Right column: Recent diary + Agent activity */}
          <div className="space-y-6">
            <RecentDiaryWidget />
            <RecentActivity />
          </div>
        </div>

        {/* Row 5: Quick actions */}
        <QuickActions />
      </div>
    </PageTransition>
  );
}

export { DashboardPage };

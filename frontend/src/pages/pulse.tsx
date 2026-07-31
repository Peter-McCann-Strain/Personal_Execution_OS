import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, Clock3, Play, Rocket, ShieldCheck, Sparkles, Waves } from "lucide-react";
import { getAgentRuns } from "@/api/agent-runs";
import { getNotifications, getWebPushConfig, listWebPushSubscriptions } from "@/api/notifications";
import {
  createScheduledAction,
  deleteScheduledAction,
  listScheduledActionRuns,
  listScheduledActions,
  runScheduledActionNow,
  updateScheduledAction,
} from "@/api/scheduled-actions";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { PageError } from "@/components/ui/page-error";
import { PageHeader } from "@/components/ui/page-header";
import { PageTransition } from "@/components/ui/page-transition";
import { Skeleton } from "@/components/ui/skeleton";
import { PERMISSION_EVENT } from "@/components/layout/proactive-notification-bridge";
import { disconnectWebPushSubscription } from "@/lib/web-push";
import { useAppStore } from "@/stores/app";
import type { ScheduledAction } from "@/types";

type ScheduleType = ScheduledAction["schedule_type"];

function PulsePage() {
  const queryClient = useQueryClient();
  const openRightPanel = useAppStore((state) => state.openRightPanel);
  const setInspectedAgentRunId = useAppStore((state) => state.setInspectedAgentRunId);
  const runtimeStreamStatus = useAppStore((state) => state.runtimeStreamStatus);

  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [scheduleType, setScheduleType] = useState<ScheduleType>("daily");
  const [hour, setHour] = useState("08");
  const [minute, setMinute] = useState("30");
  const [weekday, setWeekday] = useState("0");
  const [monthDay, setMonthDay] = useState("1");
  const [runAt, setRunAt] = useState("");
  const [deliveryChannel, setDeliveryChannel] =
    useState<ScheduledAction["delivery_channel"]>("web");
  const [editingActionId, setEditingActionId] = useState<string | null>(null);
  const [permissionState, setPermissionState] = useState(
    typeof Notification === "undefined" ? "unsupported" : Notification.permission,
  );
  const [pushRiskAccepted, setPushRiskAccepted] = useState(false);

  const scheduledActionsQuery = useQuery({
    queryKey: ["pulse", "scheduled-actions"],
    queryFn: () => listScheduledActions({ limit: 50 }),
  });
  const scheduledRunsQuery = useQuery({
    queryKey: ["pulse", "scheduled-action-runs"],
    queryFn: () => listScheduledActionRuns(),
  });
  const proactiveNotificationsQuery = useQuery({
    queryKey: ["pulse", "notifications"],
    queryFn: () => getNotifications({ limit: 12, category: "proactive" }),
  });
  const webPushConfigQuery = useQuery({
    queryKey: ["pulse", "web-push-config"],
    queryFn: () => getWebPushConfig(),
  });
  const webPushSubscriptionsQuery = useQuery({
    queryKey: ["pulse", "web-push-subscriptions"],
    queryFn: () => listWebPushSubscriptions(),
  });
  const agentRunsQuery = useQuery({
    queryKey: ["pulse", "agent-runs"],
    queryFn: () => getAgentRuns({ limit: 12 }),
  });

  const createMutation = useMutation({
    mutationFn: (data: Parameters<typeof createScheduledAction>[0]) => createScheduledAction(data),
    onSuccess: () => {
      resetComposer();
      queryClient.invalidateQueries({ queryKey: ["pulse", "scheduled-actions"] });
    },
  });

  const actionMutation = useMutation({
    mutationFn: ({ actionId, data }: { actionId: string; data: Partial<ScheduledAction> }) =>
      updateScheduledAction(actionId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pulse", "scheduled-actions"] });
    },
  });
  const deleteMutation = useMutation({
    mutationFn: (actionId: string) => deleteScheduledAction(actionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pulse", "scheduled-actions"] });
      if (editingActionId) {
        resetComposer();
      }
    },
  });
  const revokeWebPushMutation = useMutation({
    mutationFn: disconnectWebPushSubscription,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pulse", "web-push-config"] });
      queryClient.invalidateQueries({ queryKey: ["pulse", "web-push-subscriptions"] });
      queryClient.invalidateQueries({ queryKey: ["notifications", "push", "config"] });
      queryClient.invalidateQueries({ queryKey: ["notifications", "push", "subscriptions"] });
    },
  });

  const runNowMutation = useMutation({
    mutationFn: (actionId: string) => runScheduledActionNow(actionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pulse", "scheduled-action-runs"] });
      queryClient.invalidateQueries({ queryKey: ["pulse", "scheduled-actions"] });
      queryClient.invalidateQueries({ queryKey: ["pulse", "notifications"] });
    },
  });

  const pendingApprovals = useMemo(
    () => (agentRunsQuery.data?.items ?? []).filter((run) => run.pending_approvals > 0),
    [agentRunsQuery.data],
  );

  async function requestNotifications(): Promise<void> {
    if (typeof Notification === "undefined") {
      setPermissionState("unsupported");
      return;
    }
    const next = await Notification.requestPermission();
    setPermissionState(next);
    if (typeof window !== "undefined") {
      window.dispatchEvent(new Event(PERMISSION_EVENT));
    }
  }

  function resetComposer(): void {
    setEditingActionId(null);
    setTitle("");
    setPrompt("");
    setScheduleType("daily");
    setHour("08");
    setMinute("30");
    setWeekday("0");
    setMonthDay("1");
    setRunAt("");
    setDeliveryChannel("web");
  }

  function loadActionIntoComposer(action: ScheduledAction): void {
    const config = action.schedule_config ?? {};
    setEditingActionId(action.id);
    setTitle(action.title);
    setPrompt(action.prompt);
    setScheduleType(action.schedule_type);
    setHour(String(config.hour ?? 8).padStart(2, "0"));
    setMinute(String(config.minute ?? 0).padStart(2, "0"));
    setWeekday(String(config.weekday ?? 0));
    setMonthDay(String(config.day ?? 1));
    setRunAt(
      action.schedule_type === "once" && typeof config.run_at === "string"
        ? config.run_at.slice(0, 16)
        : "",
    );
    setDeliveryChannel(action.delivery_channel);
  }

  function saveScheduledAction(): void {
    const payload = {
      title,
      prompt,
      schedule_type: scheduleType,
      schedule_config: buildScheduleConfig({
        scheduleType,
        hour,
        minute,
        weekday,
        monthDay,
        runAt,
      }),
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
      delivery_channel: deliveryChannel,
    };

    if (editingActionId) {
      actionMutation.mutate(
        {
          actionId: editingActionId,
          data: payload,
        },
        {
          onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["pulse", "scheduled-actions"] });
            resetComposer();
          },
        },
      );
      return;
    }
    createMutation.mutate(payload);
  }

  return (
    <PageTransition>
      <div className="flex flex-col gap-6 p-6">
        <PageHeader
          title="Pulse"
          subtitle="Proactive runs, approvals, scheduled actions, and delivery state."
          icon={Waves}
          agentColor="notification"
        />

        <div className="flex flex-wrap gap-2">
          <Badge
            size="sm"
            variant={
              runtimeStreamStatus === "live"
                ? "success"
                : runtimeStreamStatus === "error"
                  ? "warning"
                  : "default"
            }
          >
            Runtime stream {runtimeStreamStatus}
          </Badge>
        </div>

        <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
          <Card padding="lg" className="gap-4">
            <div>
              <h2 className="text-base font-semibold text-[var(--color-fg-primary)]">
                New Scheduled Action
              </h2>
              <p className="mt-1 text-sm text-[var(--color-fg-secondary)]">
                Create proactive work without leaving the product. One scheduler, visible runs, no
                hidden cron sprawl.
              </p>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div className="md:col-span-2">
                <label className="mb-1 block text-xs font-medium text-[var(--color-fg-secondary)]">
                  Title
                </label>
                <Input
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  placeholder="Morning research scan"
                />
              </div>
              <div className="md:col-span-2">
                <label className="mb-1 block text-xs font-medium text-[var(--color-fg-secondary)]">
                  Prompt
                </label>
                <textarea
                  value={prompt}
                  onChange={(event) => setPrompt(event.target.value)}
                  rows={4}
                  className="w-full rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] px-3 py-2 text-sm text-[var(--color-fg-primary)]"
                  placeholder="Summarize urgent new inputs, flag blockers, and produce one actionable next move."
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-[var(--color-fg-secondary)]">
                  Schedule
                </label>
                <select
                  value={scheduleType}
                  onChange={(event) => setScheduleType(event.target.value as ScheduleType)}
                  className="h-9 w-full rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] px-3 text-sm text-[var(--color-fg-primary)]"
                >
                  <option value="once">One-off</option>
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                  <option value="monthly">Monthly</option>
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-[var(--color-fg-secondary)]">
                  Delivery
                </label>
                <select
                  value={deliveryChannel}
                  onChange={(event) =>
                    setDeliveryChannel(event.target.value as ScheduledAction["delivery_channel"])
                  }
                  className="h-9 w-full rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] px-3 text-sm text-[var(--color-fg-primary)]"
                >
                  <option value="web">Web inbox</option>
                  <option value="telegram">Telegram</option>
                  <option value="email">Email</option>
                </select>
              </div>
              {scheduleType === "once" ? (
                <div className="md:col-span-2">
                  <label className="mb-1 block text-xs font-medium text-[var(--color-fg-secondary)]">
                    Run at
                  </label>
                  <Input
                    type="datetime-local"
                    value={runAt}
                    onChange={(event) => setRunAt(event.target.value)}
                  />
                </div>
              ) : (
                <>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-[var(--color-fg-secondary)]">
                      Hour
                    </label>
                    <Input value={hour} onChange={(event) => setHour(event.target.value)} />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-[var(--color-fg-secondary)]">
                      Minute
                    </label>
                    <Input value={minute} onChange={(event) => setMinute(event.target.value)} />
                  </div>
                </>
              )}
              {scheduleType === "weekly" ? (
                <div>
                  <label className="mb-1 block text-xs font-medium text-[var(--color-fg-secondary)]">
                    Weekday
                  </label>
                  <select
                    value={weekday}
                    onChange={(event) => setWeekday(event.target.value)}
                    className="h-9 w-full rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] px-3 text-sm text-[var(--color-fg-primary)]"
                  >
                    <option value="0">Monday</option>
                    <option value="1">Tuesday</option>
                    <option value="2">Wednesday</option>
                    <option value="3">Thursday</option>
                    <option value="4">Friday</option>
                    <option value="5">Saturday</option>
                    <option value="6">Sunday</option>
                  </select>
                </div>
              ) : null}
              {scheduleType === "monthly" ? (
                <div>
                  <label className="mb-1 block text-xs font-medium text-[var(--color-fg-secondary)]">
                    Day of month
                  </label>
                  <Input value={monthDay} onChange={(event) => setMonthDay(event.target.value)} />
                </div>
              ) : null}
            </div>

            <div className="flex justify-end">
              {editingActionId ? (
                <Button variant="outline" className="mr-2" onClick={resetComposer}>
                  Cancel edit
                </Button>
              ) : null}
              <Button
                loading={
                  createMutation.isPending || (actionMutation.isPending && Boolean(editingActionId))
                }
                disabled={!title.trim() || !prompt.trim()}
                onClick={saveScheduledAction}
              >
                <Rocket className="h-4 w-4" />
                {editingActionId ? "Update action" : "Create action"}
              </Button>
            </div>
          </Card>

          <Card padding="lg" className="gap-4">
            <div>
              <h2 className="text-base font-semibold text-[var(--color-fg-primary)]">
                Delivery Readiness
              </h2>
              <p className="mt-1 text-sm text-[var(--color-fg-secondary)]">
                Web notifications and approval surfaces for proactive work.
              </p>
            </div>

            <div className="rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] p-4">
              <div className="flex items-center gap-2">
                <BellRing className="h-4 w-4 text-[var(--color-fg-tertiary)]" />
                <span className="text-sm font-medium text-[var(--color-fg-primary)]">
                  Browser notifications
                </span>
                <Badge
                  size="sm"
                  variant={
                    permissionState === "granted"
                      ? "success"
                      : permissionState === "denied"
                        ? "error"
                        : "default"
                  }
                >
                  {permissionState}
                </Badge>
              </div>
              <p className="mt-2 text-sm text-[var(--color-fg-secondary)]">
                Notifications can appear on a locked screen. Payloads are encrypted, but the
                browser&apos;s push service can still observe endpoint, timing, and approximate
                message-size metadata. Generic notification text is used by default; content
                previews require an explicit server-side opt-in.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Badge size="sm" variant={webPushConfigQuery.data?.enabled ? "success" : "default"}>
                  {webPushConfigQuery.data?.enabled ? "Server push ready" : "Server push disabled"}
                </Badge>
                <Badge size="sm">
                  {webPushSubscriptionsQuery.data?.length ?? 0} browser
                  {(webPushSubscriptionsQuery.data?.length ?? 0) === 1 ? "" : "s"}
                </Badge>
              </div>
              <label className="mt-3 flex items-start gap-2 text-xs text-[var(--color-fg-secondary)]">
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={pushRiskAccepted}
                  onChange={(event) => setPushRiskAccepted(event.target.checked)}
                />
                <span>
                  I understand the lock-screen and push-provider metadata exposure and want to
                  enable browser notifications on this device.
                </span>
              </label>
              <div className="mt-3">
                <Button
                  variant="outline"
                  disabled={permissionState === "unsupported" || !pushRiskAccepted}
                  onClick={() => void requestNotifications()}
                >
                  Request permission
                </Button>
              </div>
              {webPushSubscriptionsQuery.isLoading ? (
                <Skeleton className="mt-3 h-16 w-full" />
              ) : (webPushSubscriptionsQuery.data?.length ?? 0) > 0 ? (
                <div className="mt-3 space-y-2">
                  {webPushSubscriptionsQuery.data?.map((subscription) => (
                    <div
                      key={subscription.id}
                      className="flex items-center justify-between rounded-[var(--radius-md)] border border-[var(--color-border-default)] px-3 py-2"
                    >
                      <div>
                        <p className="text-sm font-medium text-[var(--color-fg-primary)]">
                          {subscription.endpoint_host ?? "Browser subscription"}
                        </p>
                        <p className="text-xs text-[var(--color-fg-tertiary)]">
                          {subscription.status}
                          {subscription.last_success_at
                            ? ` • last ok ${new Date(subscription.last_success_at).toLocaleString("en-GB")}`
                            : ""}
                        </p>
                      </div>
                      <Button
                        variant="ghost"
                        loading={
                          revokeWebPushMutation.isPending &&
                          revokeWebPushMutation.variables?.id === subscription.id
                        }
                        onClick={() => revokeWebPushMutation.mutate(subscription)}
                      >
                        Disconnect
                      </Button>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="mt-3 text-sm text-[var(--color-fg-tertiary)]">
                  No browser has completed server push registration yet.
                </p>
              )}
            </div>

            <div className="rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] p-4">
              <div className="flex items-center gap-2">
                <ShieldCheck className="h-4 w-4 text-[var(--color-fg-tertiary)]" />
                <span className="text-sm font-medium text-[var(--color-fg-primary)]">
                  Pending approvals
                </span>
              </div>
              {agentRunsQuery.isLoading ? (
                <Skeleton className="mt-3 h-24 w-full" />
              ) : pendingApprovals.length === 0 ? (
                <p className="mt-2 text-sm text-[var(--color-fg-tertiary)]">
                  No pending run approvals right now.
                </p>
              ) : (
                <div className="mt-3 space-y-2">
                  {pendingApprovals.slice(0, 4).map((run) => (
                    <button
                      key={run.id}
                      type="button"
                      onClick={() => {
                        setInspectedAgentRunId(run.id);
                        openRightPanel("agent-run");
                      }}
                      className="flex w-full items-center justify-between rounded-[var(--radius-md)] border border-[var(--color-border-default)] px-3 py-2 text-left hover:bg-[var(--color-bg-overlay)]"
                    >
                      <div>
                        <p className="text-sm font-medium text-[var(--color-fg-primary)]">
                          {run.specialist ?? "assistant"} run
                        </p>
                        <p className="text-xs text-[var(--color-fg-tertiary)]">
                          {run.pending_approvals} approval{run.pending_approvals === 1 ? "" : "s"}
                        </p>
                      </div>
                      <Badge size="sm" variant="warning">
                        Review
                      </Badge>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </Card>
        </div>

        <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
          <Card padding="lg" className="gap-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-base font-semibold text-[var(--color-fg-primary)]">
                  Scheduled Actions
                </h2>
                <p className="mt-1 text-sm text-[var(--color-fg-secondary)]">
                  Visible, editable proactive work. No silent background jobs.
                </p>
              </div>
              <Badge size="sm">{scheduledActionsQuery.data?.items.length ?? 0}</Badge>
            </div>

            {scheduledActionsQuery.isError ? (
              <PageError
                message={(scheduledActionsQuery.error as Error).message}
                onRetry={() => scheduledActionsQuery.refetch()}
              />
            ) : scheduledActionsQuery.isLoading ? (
              <div className="space-y-3">
                <Skeleton className="h-24 w-full" />
                <Skeleton className="h-24 w-full" />
              </div>
            ) : (scheduledActionsQuery.data?.items.length ?? 0) === 0 ? (
              <EmptyState
                icon={Clock3}
                title="No scheduled actions yet"
                description="Create recurring proactive work above."
              />
            ) : (
              <div className="space-y-3">
                {scheduledActionsQuery.data?.items.map((action) => (
                  <div
                    key={action.id}
                    className="rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-4"
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <h3 className="text-sm font-semibold text-[var(--color-fg-primary)]">
                          {action.title}
                        </h3>
                        <p className="mt-1 text-xs text-[var(--color-fg-secondary)]">
                          {action.schedule_type} · {action.delivery_channel} · next{" "}
                          {action.next_run_at
                            ? new Date(action.next_run_at).toLocaleString("en-GB")
                            : "not scheduled"}
                        </p>
                        {action.last_result_summary ? (
                          <p className="mt-2 text-sm text-[var(--color-fg-tertiary)]">
                            {action.last_result_summary}
                          </p>
                        ) : null}
                      </div>
                      <Badge
                        size="sm"
                        variant={
                          action.status === "active"
                            ? "success"
                            : action.status === "paused"
                              ? "warning"
                              : "default"
                        }
                      >
                        {action.status}
                      </Badge>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        loading={runNowMutation.isPending && runNowMutation.variables === action.id}
                        onClick={() => runNowMutation.mutate(action.id)}
                      >
                        <Play className="h-3.5 w-3.5" />
                        Run now
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        loading={
                          actionMutation.isPending &&
                          actionMutation.variables?.actionId === action.id
                        }
                        onClick={() =>
                          actionMutation.mutate({
                            actionId: action.id,
                            data: { status: action.status === "active" ? "paused" : "active" },
                          })
                        }
                      >
                        {action.status === "active" ? "Pause" : "Resume"}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => loadActionIntoComposer(action)}
                      >
                        Edit
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        loading={deleteMutation.isPending && deleteMutation.variables === action.id}
                        onClick={() => deleteMutation.mutate(action.id)}
                      >
                        Delete
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>

          <div className="space-y-4">
            <Card padding="lg" className="gap-4">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-base font-semibold text-[var(--color-fg-primary)]">
                    Recent Runs
                  </h2>
                  <p className="mt-1 text-sm text-[var(--color-fg-secondary)]">
                    The execution ledger for proactive work.
                  </p>
                </div>
                <Sparkles className="h-4 w-4 text-[var(--color-fg-tertiary)]" />
              </div>
              {scheduledRunsQuery.isLoading ? (
                <Skeleton className="h-24 w-full" />
              ) : (scheduledRunsQuery.data?.length ?? 0) === 0 ? (
                <p className="text-sm text-[var(--color-fg-tertiary)]">No runs recorded yet.</p>
              ) : (
                <div className="space-y-3">
                  {scheduledRunsQuery.data?.slice(0, 6).map((run) => (
                    <div
                      key={run.id}
                      className="rounded-[var(--radius-md)] border border-[var(--color-border-default)] px-3 py-2"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <Badge
                          size="sm"
                          variant={
                            run.status === "completed"
                              ? "success"
                              : run.status === "failed"
                                ? "error"
                                : "warning"
                          }
                        >
                          {run.status}
                        </Badge>
                        <span className="text-xs text-[var(--color-fg-tertiary)]">
                          {new Date(run.triggered_at).toLocaleString("en-GB")}
                        </span>
                      </div>
                      <p className="mt-2 text-sm text-[var(--color-fg-secondary)]">
                        {run.result_summary ?? run.error_message ?? "No summary available"}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </Card>

            <Card padding="lg" className="gap-4">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-base font-semibold text-[var(--color-fg-primary)]">
                    Proactive Inbox
                  </h2>
                  <p className="mt-1 text-sm text-[var(--color-fg-secondary)]">
                    Web-visible output from scheduled work and follow-up alerts.
                  </p>
                </div>
                <Badge size="sm">{proactiveNotificationsQuery.data?.items.length ?? 0}</Badge>
              </div>
              {proactiveNotificationsQuery.isLoading ? (
                <Skeleton className="h-24 w-full" />
              ) : (proactiveNotificationsQuery.data?.items.length ?? 0) === 0 ? (
                <p className="text-sm text-[var(--color-fg-tertiary)]">
                  No proactive notifications yet.
                </p>
              ) : (
                <div className="space-y-3">
                  {proactiveNotificationsQuery.data?.items.map((notification) => (
                    <div
                      key={notification.id}
                      className="rounded-[var(--radius-md)] border border-[var(--color-border-default)] px-3 py-2"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <Badge size="sm" variant="info">
                          {notification.priority}
                        </Badge>
                        <span className="text-xs text-[var(--color-fg-tertiary)]">
                          {new Date(notification.created_at).toLocaleString("en-GB")}
                        </span>
                      </div>
                      <p className="mt-2 text-sm text-[var(--color-fg-secondary)]">
                        {notification.message}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </div>
        </div>
      </div>
    </PageTransition>
  );
}

function buildScheduleConfig({
  scheduleType,
  hour,
  minute,
  weekday,
  monthDay,
  runAt,
}: {
  scheduleType: ScheduleType;
  hour: string;
  minute: string;
  weekday: string;
  monthDay: string;
  runAt: string;
}): Record<string, unknown> {
  if (scheduleType === "once") {
    return { run_at: runAt ? new Date(runAt).toISOString() : undefined };
  }
  const config: Record<string, unknown> = {
    hour: Number(hour || 8),
    minute: Number(minute || 0),
  };
  if (scheduleType === "weekly") {
    config.weekday = Number(weekday || 0);
  }
  if (scheduleType === "monthly") {
    config.day = Number(monthDay || 1);
  }
  return config;
}

export { PulsePage };

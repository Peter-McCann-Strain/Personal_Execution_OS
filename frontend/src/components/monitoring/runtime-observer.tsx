import { useQuery } from "@tanstack/react-query";
import { Activity, RadioTower, ShieldAlert, Waypoints } from "lucide-react";
import {
  getChannelMetrics,
  getEvalOutcomes,
  getSecurityMetrics,
  getTelegramWebhookStatus,
  getTraceSummaries,
} from "@/api/monitoring";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatRelativeTime } from "@/lib/utils";

function statusVariant(
  status:
    "ok" | "warn" | "fail" | "skipped" | "degraded" | "lagging" | "down" | "success" | "error",
): "success" | "warning" | "error" | "default" {
  if (status === "ok" || status === "success") return "success";
  if (status === "warn" || status === "degraded" || status === "lagging") return "warning";
  if (status === "fail" || status === "down" || status === "error") return "error";
  return "default";
}

function RuntimeObserver() {
  const traces = useQuery({
    queryKey: ["monitoring", "traces"],
    queryFn: () => getTraceSummaries(12),
    refetchInterval: 60_000,
  });

  const evals = useQuery({
    queryKey: ["monitoring", "eval-outcomes"],
    queryFn: () => getEvalOutcomes(12),
    refetchInterval: 60_000,
  });

  const channels = useQuery({
    queryKey: ["monitoring", "channel-metrics"],
    queryFn: () => getChannelMetrics(250),
    refetchInterval: 120_000,
  });

  const webhook = useQuery({
    queryKey: ["monitoring", "telegram-webhook"],
    queryFn: () => getTelegramWebhookStatus(),
    refetchInterval: 60_000,
  });
  const security = useQuery({
    queryKey: ["monitoring", "security-metrics"],
    queryFn: () => getSecurityMetrics(),
    refetchInterval: 120_000,
  });
  const traceItems = traces.data ?? [];
  const evalItems = evals.data ?? [];
  const channelItems = channels.data ?? [];
  const securityMetrics = security.data;
  const renderFailures = channelItems.reduce((sum, item) => sum + item.render_failures, 0);
  const degradedTraces = traceItems.filter((item) => item.status !== "success").length;
  const securityIssueCount = securityMetrics
    ? securityMetrics.mutating_without_confirmation_count +
      securityMetrics.duplicate_idempotency_key_count +
      securityMetrics.suspicious_tool_receipt_count
    : 0;

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-5">
        <SummaryCard
          icon={Waypoints}
          label="Recent Traces"
          value={traceItems.length}
          helper={`${degradedTraces} degraded or errored`}
          loading={traces.isLoading}
          tone="info"
        />
        <SummaryCard
          icon={Activity}
          label="Eval Outcomes"
          value={evalItems.length}
          helper={`${evalItems.filter((item) => item.eval_status !== "auto_scored").length} non-default statuses`}
          loading={evals.isLoading}
          tone="success"
        />
        <SummaryCard
          icon={ShieldAlert}
          label="Render Failures"
          value={renderFailures}
          helper={`${channelItems.length} active channels`}
          loading={channels.isLoading}
          tone={renderFailures > 0 ? "warning" : "success"}
        />
        <SummaryCard
          icon={RadioTower}
          label="Telegram Webhook"
          value={webhook.data?.status ?? "unknown"}
          helper={
            webhook.data?.pending_update_count != null
              ? `${webhook.data.pending_update_count} pending updates`
              : "No webhook backlog data"
          }
          loading={webhook.isLoading}
          tone={
            webhook.data?.status === "ok"
              ? "success"
              : webhook.data?.status === "degraded" || webhook.data?.status === "lagging"
                ? "warning"
                : "error"
          }
          badge
        />
        <SummaryCard
          icon={ShieldAlert}
          label="Security Signals"
          value={securityIssueCount}
          helper={
            securityMetrics
              ? `${securityMetrics.policy_decision_count} policy decisions`
              : "No security metrics yet"
          }
          loading={security.isLoading}
          tone={securityIssueCount > 0 ? "warning" : "success"}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1.1fr_0.9fr]">
        <Card padding="none">
          <CardHeader>
            <CardTitle>Recent Traces</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {traces.isLoading ? (
              Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-16" />)
            ) : traces.isError ? (
              <ErrorText message={(traces.error as Error).message} />
            ) : traceItems.length === 0 ? (
              <EmptyText message="No traces have been recorded yet." />
            ) : (
              traceItems.map((trace) => (
                <div
                  key={trace.trace_id}
                  className="rounded-[var(--radius-md)] border border-[var(--color-border-subtle)] bg-[var(--color-bg-base)] px-3 py-3"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-sm font-semibold text-[var(--color-fg-primary)]">
                      {trace.specialist ?? "unassigned"} · {trace.channel}
                    </p>
                    <Badge
                      variant={statusVariant(trace.status as "success" | "degraded" | "error")}
                      size="sm"
                    >
                      {trace.status}
                    </Badge>
                  </div>
                  <div className="mt-2 grid grid-cols-1 gap-1 text-xs text-[var(--color-fg-secondary)] md:grid-cols-2">
                    <p>Trace: {trace.trace_id.slice(0, 12)}</p>
                    <p>Latency: {trace.total_latency_ms} ms</p>
                    <p>Spans: {trace.span_count}</p>
                    <p>Errors: {trace.error_count}</p>
                  </div>
                  <p className="mt-2 text-xs text-[var(--color-fg-tertiary)]">
                    {formatRelativeTime(new Date(trace.created_at))}
                  </p>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        <div className="grid grid-cols-1 gap-4">
          <Card padding="none">
            <CardHeader>
              <CardTitle>Channel Metrics</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {channels.isLoading ? (
                Array.from({ length: 3 }).map((_, index) => (
                  <Skeleton key={index} className="h-14" />
                ))
              ) : channels.isError ? (
                <ErrorText message={(channels.error as Error).message} />
              ) : channelItems.length === 0 ? (
                <EmptyText message="No channel metrics are available yet." />
              ) : (
                channelItems.map((metric) => (
                  <div
                    key={metric.source}
                    className="flex items-center justify-between rounded-[var(--radius-md)] border border-[var(--color-border-subtle)] bg-[var(--color-bg-base)] px-3 py-2"
                  >
                    <div>
                      <p className="text-sm font-medium text-[var(--color-fg-primary)]">
                        {metric.source}
                      </p>
                      <p className="text-xs text-[var(--color-fg-secondary)]">
                        {metric.interaction_count} interactions · {metric.avg_chunk_count} avg
                        chunks · {metric.avg_retry_count} avg retries
                      </p>
                    </div>
                    <div className="text-right text-xs text-[var(--color-fg-secondary)]">
                      <p>{metric.avg_latency_ms} ms</p>
                      <p>{metric.render_failures} render failures</p>
                      <p>{metric.delivery_failures} delivery failures</p>
                    </div>
                  </div>
                ))
              )}
            </CardContent>
          </Card>

          <Card padding="none">
            <CardHeader>
              <CardTitle>Recent Eval Outcomes</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {evals.isLoading ? (
                Array.from({ length: 3 }).map((_, index) => (
                  <Skeleton key={index} className="h-16" />
                ))
              ) : evals.isError ? (
                <ErrorText message={(evals.error as Error).message} />
              ) : evalItems.length === 0 ? (
                <EmptyText message="No evaluation outcomes have been recorded yet." />
              ) : (
                evalItems.map((outcome) => (
                  <div
                    key={outcome.id}
                    className="rounded-[var(--radius-md)] border border-[var(--color-border-subtle)] bg-[var(--color-bg-base)] px-3 py-3"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-sm font-semibold text-[var(--color-fg-primary)]">
                        {outcome.specialist} · {outcome.source}
                      </p>
                      <Badge variant="default" size="sm">
                        {outcome.eval_status}
                      </Badge>
                      {outcome.feedback_rating && (
                        <Badge variant="default" size="sm">
                          {outcome.feedback_rating}
                        </Badge>
                      )}
                    </div>
                    <p className="mt-2 text-xs text-[var(--color-fg-secondary)]">
                      Final response quality: {formatQualityValue(outcome.quality_scores)}
                    </p>
                    <p className="mt-1 text-xs text-[var(--color-fg-tertiary)]">
                      {formatRelativeTime(new Date(outcome.created_at))}
                    </p>
                  </div>
                ))
              )}
            </CardContent>
          </Card>

          <Card padding="none">
            <CardHeader>
              <CardTitle>Webhook State</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {webhook.isLoading ? (
                <Skeleton className="h-24" />
              ) : webhook.isError ? (
                <ErrorText message={(webhook.error as Error).message} />
              ) : webhook.data ? (
                <div className="rounded-[var(--radius-md)] border border-[var(--color-border-subtle)] bg-[var(--color-bg-base)] px-3 py-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-sm font-semibold text-[var(--color-fg-primary)]">
                      Telegram delivery
                    </p>
                    <Badge
                      variant={statusVariant(
                        webhook.data.status as "ok" | "degraded" | "lagging" | "error",
                      )}
                      size="sm"
                    >
                      {webhook.data.status}
                    </Badge>
                  </div>
                  <div className="mt-2 space-y-1 text-xs text-[var(--color-fg-secondary)]">
                    <p>Pending updates: {webhook.data.pending_update_count ?? "n/a"}</p>
                    <p>Lagging: {webhook.data.webhook_lagging ? "yes" : "no"}</p>
                    <p>Max connections: {webhook.data.max_connections ?? "n/a"}</p>
                    <p>Last error age: {webhook.data.last_error_age_seconds ?? "n/a"} s</p>
                    <p>Last error: {webhook.data.last_error_message ?? "none"}</p>
                  </div>
                </div>
              ) : (
                <EmptyText message="Webhook state is unavailable." />
              )}
            </CardContent>
          </Card>

          <Card padding="none">
            <CardHeader>
              <CardTitle>Security Metrics</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {security.isLoading ? (
                <Skeleton className="h-24" />
              ) : security.isError ? (
                <ErrorText message={(security.error as Error).message} />
              ) : securityMetrics ? (
                <div className="rounded-[var(--radius-md)] border border-[var(--color-border-subtle)] bg-[var(--color-bg-base)] px-3 py-3">
                  <div className="space-y-1 text-xs text-[var(--color-fg-secondary)]">
                    <p>Instruction-risk decisions: {securityMetrics.instruction_risk_decisions}</p>
                    <p>Trust-boundary denies: {securityMetrics.trust_boundary_denies}</p>
                    <p>
                      Mutations without confirmation:{" "}
                      {securityMetrics.mutating_without_confirmation_count}
                    </p>
                    <p>
                      Duplicate idempotency keys: {securityMetrics.duplicate_idempotency_key_count}
                    </p>
                    <p>Suspicious tool receipts: {securityMetrics.suspicious_tool_receipt_count}</p>
                  </div>
                </div>
              ) : (
                <EmptyText message="Security metrics are unavailable." />
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

function SummaryCard({
  icon: Icon,
  label,
  value,
  helper,
  loading,
  tone,
  badge = false,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: number | string;
  helper: string;
  loading: boolean;
  tone: "info" | "success" | "warning" | "error";
  badge?: boolean;
}) {
  const toneClass = {
    info: "text-[var(--color-info-500)]",
    success: "text-[var(--color-success-500)]",
    warning: "text-[var(--color-warning-500)]",
    error: "text-[var(--color-error-500)]",
  }[tone];

  return (
    <Card>
      <div className="flex items-center gap-3">
        <Icon className={`h-5 w-5 ${toneClass}`} />
        <div>
          <p className="text-xs uppercase tracking-wide text-[var(--color-fg-tertiary)]">{label}</p>
          {loading ? (
            <Skeleton className="mt-2 h-7 w-24" />
          ) : badge ? (
            <div className="mt-1">
              <Badge
                variant={statusVariant(String(value) as "ok" | "degraded" | "error")}
                size="md"
              >
                {String(value)}
              </Badge>
            </div>
          ) : (
            <p className="text-2xl font-semibold text-[var(--color-fg-primary)]">{value}</p>
          )}
          <p className="mt-1 text-xs text-[var(--color-fg-secondary)]">{helper}</p>
        </div>
      </div>
    </Card>
  );
}

function formatQualityValue(qualityScores: Record<string, number | string | null> | null) {
  const value = qualityScores?.final_response_quality;
  return typeof value === "number" ? value.toFixed(2) : "n/a";
}

function ErrorText({ message }: { message: string }) {
  return <p className="text-sm text-[var(--color-error-500)]">{message}</p>;
}

function EmptyText({ message }: { message: string }) {
  return <p className="text-sm text-[var(--color-fg-secondary)]">{message}</p>;
}

export { RuntimeObserver };

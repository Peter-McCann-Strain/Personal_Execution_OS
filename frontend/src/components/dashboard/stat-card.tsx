import { useId } from "react";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import { AreaChart, Area, ResponsiveContainer, YAxis } from "recharts";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import type { AgentName } from "@/types";

const agentBorderColor: Record<AgentName, string> = {
  diary: "var(--color-agent-diary)",
  memory: "var(--color-agent-memory)",
  research: "var(--color-agent-research)",
  review: "var(--color-agent-review)",
  project: "var(--color-agent-project)",
  communications: "var(--color-agent-comms)",
  tools: "var(--color-agent-tools)",
  notification: "var(--color-agent-notif)",
  save: "var(--color-agent-memory)",
  plan_day: "var(--color-agent-project)",
  socratic: "var(--color-agent-socratic)",
};

interface StatCardProps {
  value: number | null;
  label: string;
  trend: number | null;
  sparkline: number[];
  subLabel?: string | null;
  agentColor: AgentName;
  emptyText?: string;
  formatValue?: (v: number) => string;
  /**
   * Categorised connector failure shown as actionable error chrome.
   * When `status === "unavailable"` we surface the category-specific message
   * and (if `actionUrl` is set) a "Reconnect" link so the user can fix it.
   */
  status?: "available" | "unavailable" | "not_configured";
  errorCategory?: "token_expired" | "rate_limited" | "backend_error" | "unknown" | null;
  actionable?: boolean;
  actionUrl?: string | null;
  errorMessage?: string | null;
}

function TrendIndicator({ trend }: { trend: number | null }) {
  if (trend == null || trend === 0) {
    return (
      <span className="inline-flex items-center gap-0.5 text-xs text-[var(--color-fg-tertiary)]">
        <Minus className="h-3 w-3" />
        <span>0%</span>
      </span>
    );
  }

  const isPositive = trend > 0;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 text-xs font-medium",
        isPositive ? "text-[var(--color-success-500)]" : "text-[var(--color-error-500)]",
      )}
    >
      {isPositive ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
      <span>
        {isPositive ? "+" : ""}
        {Number.isInteger(trend) ? trend : trend.toFixed(1)}
      </span>
    </span>
  );
}

function MiniSparkline({
  data,
  color,
  gradientId,
}: {
  data: number[];
  color: string;
  gradientId: string;
}) {
  if (data.length === 0) return null;

  const chartData = data.map((v, i) => ({ idx: i, value: v }));

  return (
    <div className="h-8 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={chartData} margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
          <YAxis hide domain={["dataMin - 1", "dataMax + 1"]} />
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={color} stopOpacity={0.3} />
              <stop offset="95%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <Area
            type="monotone"
            dataKey="value"
            stroke={color}
            strokeWidth={1.5}
            fill={`url(#${gradientId})`}
            dot={false}
            animationDuration={600}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function ConnectorErrorBlock({
  category,
  message,
  actionable,
  actionUrl,
}: {
  category: NonNullable<StatCardProps["errorCategory"]>;
  message: string;
  actionable: boolean;
  actionUrl?: string | null;
}) {
  const tone = category === "token_expired" ? "var(--color-warning-500)" : "var(--color-error-500)";
  return (
    <div
      className="mt-1 space-y-1 rounded-[var(--radius-sm)] border px-2 py-1.5"
      style={{ borderColor: tone, color: tone }}
      data-testid="stat-card-error"
      data-category={category}
    >
      <p className="text-xs font-medium leading-snug">{message}</p>
      {actionable && actionUrl ? (
        <a
          href={actionUrl}
          className="inline-flex items-center text-[11px] font-semibold underline"
          data-testid="stat-card-reconnect"
        >
          Reconnect
        </a>
      ) : null}
    </div>
  );
}

export function StatCard({
  value,
  label,
  trend,
  sparkline,
  subLabel,
  agentColor,
  emptyText = "No data yet",
  formatValue,
  status = "available",
  errorCategory = null,
  actionable = false,
  actionUrl = null,
  errorMessage = null,
}: StatCardProps) {
  const borderColor = agentBorderColor[agentColor];
  const gradientId = useId();
  const isError = status === "unavailable" && errorCategory != null;

  return (
    <div
      className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-4 border-l-2"
      style={{ borderLeftColor: borderColor }}
    >
      <p className="text-xs font-medium uppercase tracking-wide text-[var(--color-fg-tertiary)]">
        {label}
      </p>

      <div className="mt-1 flex items-baseline gap-2">
        <span className="text-3xl font-bold tabular-nums text-[var(--color-fg-primary)]">
          {value != null ? (formatValue ? formatValue(value) : value) : "--"}
        </span>
        <TrendIndicator trend={trend} />
      </div>

      {subLabel && <p className="mt-0.5 text-xs text-[var(--color-fg-secondary)]">{subLabel}</p>}

      {isError ? (
        <ConnectorErrorBlock
          category={errorCategory}
          message={errorMessage ?? emptyText}
          actionable={actionable}
          actionUrl={actionUrl}
        />
      ) : value == null ? (
        <p className="mt-1 text-xs text-[var(--color-fg-tertiary)]">{emptyText}</p>
      ) : null}

      <div className="mt-2">
        <MiniSparkline data={sparkline} color={borderColor} gradientId={gradientId} />
      </div>
    </div>
  );
}

export function StatCardSkeleton() {
  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-4">
      <Skeleton className="h-3 w-24" />
      <Skeleton className="mt-2 h-8 w-16" />
      <Skeleton className="mt-3 h-8 w-full" />
    </div>
  );
}

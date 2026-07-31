import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { cn, formatCurrency, formatTokens } from "@/lib/utils";
import { AGENT_CHART_COLORS } from "@/lib/agent-utils";
import { formatLatency } from "@/lib/date";
import { type Period, PERIOD_OPTIONS, CHART_TOOLTIP_STYLE } from "@/lib/monitoring";
import { Card } from "@/components/ui/card";
import { AgentBadge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { getAgentComparison } from "@/api/monitoring";
import type { AgentName } from "@/types";

// ─── AgentComparison Component ──────────────────────────────

function AgentComparison() {
  const [period, setPeriod] = useState<Period>("7d");

  const { data, isLoading } = useQuery({
    queryKey: ["agent-comparison", period],
    queryFn: () => getAgentComparison(period),
  });

  if (isLoading) {
    return (
      <div className="flex flex-col gap-6">
        <Skeleton className="h-8 w-48" />
        <div className="grid grid-cols-2 gap-4">
          <Skeleton className="h-72" />
          <Skeleton className="h-72" />
        </div>
        <Skeleton className="h-64" />
      </div>
    );
  }

  const summaries = data?.summaries ?? [];
  const distribution = data?.usage_distribution ?? [];

  const pieData = distribution.map((d) => ({
    name: d.agent,
    value: d.calls,
  }));

  const totalCalls = distribution.reduce((sum, d) => sum + d.calls, 0);

  return (
    <div className="flex flex-col gap-6">
      {/* Header + Period Selector */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-[var(--color-fg-primary)]">
          Agent Performance Comparison
        </h2>
        <SegmentedControl
          value={period}
          onChange={setPeriod}
          options={PERIOD_OPTIONS}
          label="Comparison period"
        />
      </div>

      {/* Usage Distribution Donut */}
      <Card padding="md">
        <h3 className="text-sm font-semibold text-[var(--color-fg-primary)] mb-4">
          Usage Distribution
        </h3>
        {pieData.length === 0 ? (
          <div className="flex items-center justify-center h-72">
            <p className="text-sm text-[var(--color-fg-tertiary)]">No data available</p>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie
                data={pieData}
                cx="50%"
                cy="50%"
                innerRadius={70}
                outerRadius={110}
                paddingAngle={2}
                dataKey="value"
                label={({ name, percent }) => {
                  const label = typeof name === "string" ? name : "Unknown";
                  const ratio = typeof percent === "number" ? percent : 0;
                  return `${label} (${(ratio * 100).toFixed(0)}%)`;
                }}
                labelLine={false}
              >
                {pieData.map((entry) => (
                  <Cell
                    key={entry.name}
                    fill={AGENT_CHART_COLORS[entry.name as AgentName] ?? "oklch(0.58 0.17 250)"}
                  />
                ))}
              </Pie>
              <Tooltip
                contentStyle={CHART_TOOLTIP_STYLE}
                formatter={(value) => [
                  `${Number(Array.isArray(value) ? value[0] : (value ?? 0))} calls`,
                  "Usage",
                ]}
              />
              <Legend
                formatter={(value: string) => (
                  <span
                    style={{
                      color: "var(--color-fg-secondary)",
                      fontSize: 12,
                    }}
                  >
                    {value}
                  </span>
                )}
              />
            </PieChart>
          </ResponsiveContainer>
        )}
        <p className="text-center text-xs text-[var(--color-fg-tertiary)] mt-2">
          {totalCalls.toLocaleString()} total calls
        </p>
      </Card>

      {/* Agent Summary Table */}
      <Card padding="none" className="overflow-hidden">
        <div className="px-4 py-3 border-b border-[var(--color-border-subtle)]">
          <h3 className="text-sm font-semibold text-[var(--color-fg-primary)]">Agent Summary</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--color-border-subtle)] bg-[var(--color-bg-elevated)]">
                <th className="px-4 py-2.5 text-left text-xs font-medium text-[var(--color-fg-tertiary)] uppercase tracking-wider">
                  Agent
                </th>
                <th className="px-4 py-2.5 text-right text-xs font-medium text-[var(--color-fg-tertiary)] uppercase tracking-wider">
                  Calls
                </th>
                <th className="px-4 py-2.5 text-right text-xs font-medium text-[var(--color-fg-tertiary)] uppercase tracking-wider">
                  Avg Cost
                </th>
                <th className="px-4 py-2.5 text-right text-xs font-medium text-[var(--color-fg-tertiary)] uppercase tracking-wider">
                  Avg Latency
                </th>
                <th className="px-4 py-2.5 text-right text-xs font-medium text-[var(--color-fg-tertiary)] uppercase tracking-wider">
                  Error Rate
                </th>
                <th className="px-4 py-2.5 text-right text-xs font-medium text-[var(--color-fg-tertiary)] uppercase tracking-wider">
                  Tokens
                </th>
              </tr>
            </thead>
            <tbody>
              {summaries.length === 0 ? (
                <tr>
                  <td
                    colSpan={6}
                    className="px-4 py-8 text-center text-sm text-[var(--color-fg-tertiary)]"
                  >
                    No data available
                  </td>
                </tr>
              ) : (
                summaries.map((summary) => (
                  <tr
                    key={summary.agent}
                    className="border-b border-[var(--color-border-subtle)] hover:bg-[var(--color-bg-overlay)] transition-colors"
                    style={{
                      borderLeftWidth: 3,
                      borderLeftColor: AGENT_CHART_COLORS[summary.agent] ?? "transparent",
                    }}
                  >
                    <td className="px-4 py-2.5">
                      <AgentBadge agent={summary.agent} size="sm" />
                    </td>
                    <td className="px-4 py-2.5 text-right text-xs text-[var(--color-fg-secondary)] font-mono">
                      {summary.call_count.toLocaleString()}
                    </td>
                    <td className="px-4 py-2.5 text-right text-xs text-[var(--color-fg-secondary)] font-mono">
                      {formatCurrency(summary.avg_cost)}
                    </td>
                    <td className="px-4 py-2.5 text-right text-xs text-[var(--color-fg-secondary)] font-mono">
                      {formatLatency(summary.avg_latency_ms)}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <span
                        className={cn(
                          "text-xs font-mono",
                          summary.error_rate > 5
                            ? "text-[var(--color-error-500)]"
                            : summary.error_rate > 2
                              ? "text-[var(--color-warning-500)]"
                              : "text-[var(--color-fg-secondary)]",
                        )}
                      >
                        {summary.error_rate.toFixed(1)}%
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-right text-xs text-[var(--color-fg-tertiary)] font-mono">
                      {formatTokens(summary.total_tokens)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

export { AgentComparison };

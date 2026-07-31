import { useState } from "react";
import { DollarSign, RefreshCw } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { formatCurrency, formatTokens } from "@/lib/utils";
import { AGENT_CHART_COLORS } from "@/lib/agent-utils";
import { type Period, PERIOD_OPTIONS, MODEL_COLORS, CHART_TOOLTIP_STYLE } from "@/lib/monitoring";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { getLLMStats } from "@/api/monitoring";

const tokenDonutColors = ["oklch(0.58 0.17 250)", "oklch(0.6 0.13 165)"];

// ─── LLMAnalytics Component ────────────────────────────────

function LLMAnalytics() {
  const [period, setPeriod] = useState<Period>("7d");
  const queryClient = useQueryClient();

  const { data: stats, isLoading } = useQuery({
    queryKey: ["llm-stats", period],
    queryFn: () => getLLMStats(period),
  });

  if (isLoading) {
    return (
      <div className="flex flex-col gap-6">
        <div className="grid grid-cols-3 gap-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
        <Skeleton className="h-64" />
        <div className="grid grid-cols-2 gap-4">
          <Skeleton className="h-64" />
          <Skeleton className="h-64" />
        </div>
      </div>
    );
  }

  const costTrendData = stats?.cost_trend ?? [];
  const costByModel = stats?.cost_by_model ?? [];
  const costByAgent = stats?.cost_by_agent ?? [];
  const tokens = stats?.tokens ?? { input: 0, output: 0 };
  const latencyByAgent = stats?.latency_by_agent ?? [];

  const tokenDonutData = [
    { name: "Input", value: tokens.input },
    { name: "Output", value: tokens.output },
  ];

  return (
    <div className="flex flex-col gap-6">
      {/* Period Selector */}
      <div className="flex items-center justify-between">
        <SegmentedControl
          value={period}
          onChange={setPeriod}
          options={PERIOD_OPTIONS}
          label="Analytics period"
        />
        <Button
          variant="ghost"
          size="icon"
          onClick={() => queryClient.invalidateQueries({ queryKey: ["llm-stats"] })}
          aria-label="Refresh analytics"
        >
          <RefreshCw className="h-4 w-4" />
        </Button>
      </div>

      {/* Cost Stat Cards */}
      <div className="grid grid-cols-3 gap-4">
        <StatCard label="Today" value={formatCurrency(stats?.cost.today ?? 0)} icon={DollarSign} />
        <StatCard
          label="This Week"
          value={formatCurrency(stats?.cost.week ?? 0)}
          icon={DollarSign}
        />
        <StatCard
          label="This Month"
          value={formatCurrency(stats?.cost.month ?? 0)}
          icon={DollarSign}
        />
      </div>

      {/* Cost Trend Chart */}
      <Card padding="md">
        <h3 className="text-sm font-semibold text-[var(--color-fg-primary)] mb-4">Cost Trend</h3>
        <ResponsiveContainer width="100%" height={260}>
          <AreaChart data={costTrendData}>
            <defs>
              <linearGradient id="costGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="oklch(0.58 0.17 250)" stopOpacity={0.3} />
                <stop offset="95%" stopColor="oklch(0.58 0.17 250)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-subtle)" />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 11, fill: "var(--color-fg-tertiary)" }}
              stroke="var(--color-border-default)"
            />
            <YAxis
              tick={{ fontSize: 11, fill: "var(--color-fg-tertiary)" }}
              stroke="var(--color-border-default)"
              tickFormatter={(v: number) => `$${v.toFixed(2)}`}
            />
            <Tooltip
              contentStyle={CHART_TOOLTIP_STYLE}
              formatter={(value) => {
                const numericValue = Number(Array.isArray(value) ? value[0] : (value ?? 0));
                return [`$${numericValue.toFixed(4)}`, "Cost"] as [string, string];
              }}
            />
            <Area
              type="monotone"
              dataKey="cost"
              stroke="oklch(0.58 0.17 250)"
              strokeWidth={2}
              fill="url(#costGradient)"
            />
          </AreaChart>
        </ResponsiveContainer>
      </Card>

      {/* Cost by Model + Cost by Agent */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Cost by Model - Horizontal Bar */}
        <Card padding="md">
          <h3 className="text-sm font-semibold text-[var(--color-fg-primary)] mb-4">
            Cost by Model
          </h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={costByModel} layout="vertical" margin={{ left: 60 }}>
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="var(--color-border-subtle)"
                horizontal={false}
              />
              <XAxis
                type="number"
                tick={{ fontSize: 11, fill: "var(--color-fg-tertiary)" }}
                stroke="var(--color-border-default)"
                tickFormatter={(v: number) => `$${v.toFixed(2)}`}
              />
              <YAxis
                dataKey="model"
                type="category"
                tick={{ fontSize: 11, fill: "var(--color-fg-tertiary)" }}
                stroke="var(--color-border-default)"
                width={55}
              />
              <Tooltip
                contentStyle={CHART_TOOLTIP_STYLE}
                formatter={(value) => {
                  const numericValue = Number(Array.isArray(value) ? value[0] : (value ?? 0));
                  return [`$${numericValue.toFixed(4)}`, "Cost"] as [string, string];
                }}
              />
              <Bar dataKey="cost" radius={[0, 4, 4, 0]}>
                {costByModel.map((entry, index) => (
                  <Cell
                    key={index}
                    fill={MODEL_COLORS[entry.model.toLowerCase()] ?? "oklch(0.58 0.17 250)"}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Card>

        {/* Cost by Agent - Horizontal Bar */}
        <Card padding="md">
          <h3 className="text-sm font-semibold text-[var(--color-fg-primary)] mb-4">
            Cost by Agent
          </h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={costByAgent} layout="vertical" margin={{ left: 80 }}>
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="var(--color-border-subtle)"
                horizontal={false}
              />
              <XAxis
                type="number"
                tick={{ fontSize: 11, fill: "var(--color-fg-tertiary)" }}
                stroke="var(--color-border-default)"
                tickFormatter={(v: number) => `$${v.toFixed(2)}`}
              />
              <YAxis
                dataKey="agent"
                type="category"
                tick={{ fontSize: 11, fill: "var(--color-fg-tertiary)" }}
                stroke="var(--color-border-default)"
                width={75}
              />
              <Tooltip
                contentStyle={CHART_TOOLTIP_STYLE}
                formatter={(value) => {
                  const numericValue = Number(Array.isArray(value) ? value[0] : (value ?? 0));
                  return [`$${numericValue.toFixed(4)}`, "Cost"] as [string, string];
                }}
              />
              <Bar dataKey="cost" radius={[0, 4, 4, 0]}>
                {costByAgent.map((entry) => (
                  <Cell
                    key={entry.agent}
                    fill={AGENT_CHART_COLORS[entry.agent] ?? "oklch(0.58 0.17 250)"}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Card>
      </div>

      {/* Token Donut + Latency by Agent */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Token Usage Donut */}
        <Card padding="md">
          <h3 className="text-sm font-semibold text-[var(--color-fg-primary)] mb-4">
            Token Usage (Input vs Output)
          </h3>
          <ResponsiveContainer width="100%" height={220}>
            <PieChart>
              <Pie
                data={tokenDonutData}
                cx="50%"
                cy="50%"
                innerRadius={60}
                outerRadius={90}
                paddingAngle={2}
                dataKey="value"
              >
                {tokenDonutData.map((_, index) => (
                  <Cell key={index} fill={tokenDonutColors[index]} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={CHART_TOOLTIP_STYLE}
                formatter={(value) => {
                  const numericValue = Number(Array.isArray(value) ? value[0] : (value ?? 0));
                  return [`${(numericValue / 1000).toFixed(1)}K`, "Tokens"] as [string, string];
                }}
              />
              <Legend
                formatter={(value: string) => (
                  <span style={{ color: "var(--color-fg-secondary)", fontSize: 12 }}>{value}</span>
                )}
              />
            </PieChart>
          </ResponsiveContainer>
          <div className="flex justify-center gap-6 text-xs text-[var(--color-fg-tertiary)]">
            <span>Input: {formatTokens(tokens.input)}</span>
            <span>Output: {formatTokens(tokens.output)}</span>
          </div>
        </Card>

        {/* Latency by Agent - Horizontal Bar */}
        <Card padding="md">
          <h3 className="text-sm font-semibold text-[var(--color-fg-primary)] mb-4">
            Avg Latency by Agent
          </h3>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={latencyByAgent} layout="vertical" margin={{ left: 80 }}>
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="var(--color-border-subtle)"
                horizontal={false}
              />
              <XAxis
                type="number"
                tick={{ fontSize: 11, fill: "var(--color-fg-tertiary)" }}
                stroke="var(--color-border-default)"
                tickFormatter={(v: number) => `${(v / 1000).toFixed(1)}s`}
              />
              <YAxis
                dataKey="agent"
                type="category"
                tick={{ fontSize: 11, fill: "var(--color-fg-tertiary)" }}
                stroke="var(--color-border-default)"
                width={75}
              />
              <Tooltip
                contentStyle={CHART_TOOLTIP_STYLE}
                formatter={(value) => {
                  const numericValue = Number(Array.isArray(value) ? value[0] : (value ?? 0));
                  return [`${numericValue.toLocaleString()}ms`, "Latency"] as [string, string];
                }}
              />
              <Bar dataKey="avg_ms" radius={[0, 4, 4, 0]}>
                {latencyByAgent.map((entry) => (
                  <Cell
                    key={entry.agent}
                    fill={AGENT_CHART_COLORS[entry.agent] ?? "oklch(0.58 0.17 250)"}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Card>
      </div>
    </div>
  );
}

// ─── StatCard ───────────────────────────────────────────────

interface StatCardProps {
  label: string;
  value: string;
  icon: LucideIcon;
}

function StatCard({ label, value, icon: Icon }: StatCardProps) {
  return (
    <Card padding="md" className="flex flex-col gap-1">
      <div className="flex items-center gap-2">
        <Icon className="h-4 w-4 text-[var(--color-fg-tertiary)]" />
        <span className="text-xs font-medium text-[var(--color-fg-tertiary)] uppercase tracking-wider">
          {label}
        </span>
      </div>
      <p className="text-2xl font-bold text-[var(--color-fg-primary)]">{value}</p>
    </Card>
  );
}

export { LLMAnalytics };

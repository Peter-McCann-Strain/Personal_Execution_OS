import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
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
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import { format, parseISO } from "date-fns";
import { getEpisodeStats } from "@/api/episodes";
import type { MoodTrendPoint, TagCount, ParaCount } from "@/api/episodes";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

// ─── Time Range Toggle ──────────────────────────────────────
const TIME_RANGES = [30, 90, 365] as const;
type TimeRange = (typeof TIME_RANGES)[number];

interface DiaryTrendsProps {
  className?: string;
}

// ─── Palette ────────────────────────────────────────────────
const PARA_COLORS: Record<string, string> = {
  project: "var(--color-agent-diary)",
  area: "var(--color-success-500)",
  resource: "var(--color-info-500)",
  archive: "var(--color-fg-tertiary)",
  unclassified: "var(--color-bg-wash)",
};

const TAG_BAR_COLORS = [
  "var(--color-agent-diary)",
  "var(--color-agent-memory)",
  "var(--color-agent-research)",
  "var(--color-agent-review)",
  "var(--color-agent-project)",
  "var(--color-agent-comms)",
  "var(--color-agent-tools)",
  "var(--color-agent-notif)",
  "var(--color-info-500)",
  "var(--color-warning-500)",
];

// ─── Custom Tooltip ─────────────────────────────────────────
function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ value: number; name: string; color: string }>;
  label?: string;
}) {
  if (!active || !payload || !label) return null;

  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] px-3 py-2 shadow-md">
      <p className="text-xs font-medium text-[var(--color-fg-primary)] mb-1">
        {(() => {
          try {
            return format(parseISO(label), "EEE d MMM");
          } catch {
            return label;
          }
        })()}
      </p>
      {payload.map((entry) => (
        <p key={entry.name} className="text-xs text-[var(--color-fg-secondary)]">
          <span
            className="inline-block h-2 w-2 rounded-full mr-1.5"
            style={{ backgroundColor: entry.color }}
          />
          {entry.name}: {entry.value != null ? entry.value.toFixed(1) : "--"}
        </p>
      ))}
    </div>
  );
}

function BarTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ value: number; payload: { tag?: string; category?: string } }>;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const item = payload[0];
  const label = item.payload.tag ?? item.payload.category ?? "";

  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] px-3 py-2 shadow-md">
      <p className="text-xs font-medium text-[var(--color-fg-primary)]">
        {label}: {item.value}
      </p>
    </div>
  );
}

// ─── Mood & Energy Area Chart ───────────────────────────────
function MoodEnergyChart({ data }: { data: MoodTrendPoint[] }) {
  const moodColor = "var(--color-agent-diary)";
  const energyColor = "var(--color-success-500)";

  if (data.length === 0) {
    return (
      <p className="text-xs text-[var(--color-fg-tertiary)] text-center py-12">
        Start journaling to see your mood trends.
      </p>
    );
  }

  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
          <defs>
            <linearGradient id="trendGradMood" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={moodColor} stopOpacity={0.2} />
              <stop offset="95%" stopColor={moodColor} stopOpacity={0} />
            </linearGradient>
            <linearGradient id="trendGradEnergy" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={energyColor} stopOpacity={0.2} />
              <stop offset="95%" stopColor={energyColor} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="var(--color-border-subtle)"
            vertical={false}
          />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 10, fill: "var(--color-fg-tertiary)" }}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v: string) => {
              try {
                return format(parseISO(v), "d MMM");
              } catch {
                return v;
              }
            }}
            interval={Math.max(0, Math.floor(data.length / 7))}
          />
          <YAxis
            domain={[0, 10]}
            tick={{ fontSize: 10, fill: "var(--color-fg-tertiary)" }}
            tickLine={false}
            axisLine={false}
            ticks={[0, 2, 4, 6, 8, 10]}
          />
          <Tooltip content={<ChartTooltip />} />
          <Area
            type="monotone"
            dataKey="mood"
            name="Mood"
            stroke={moodColor}
            strokeWidth={2}
            fill="url(#trendGradMood)"
            dot={false}
            connectNulls
            animationDuration={600}
          />
          <Area
            type="monotone"
            dataKey="energy"
            name="Energy"
            stroke={energyColor}
            strokeWidth={1.5}
            strokeDasharray="4 3"
            fill="url(#trendGradEnergy)"
            dot={false}
            connectNulls
            animationDuration={600}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

// ─── Tag Frequency Bar Chart ────────────────────────────────
function TagFrequencyChart({ data }: { data: TagCount[] }) {
  if (data.length === 0) {
    return (
      <p className="text-xs text-[var(--color-fg-tertiary)] text-center py-8">
        No tag data available.
      </p>
    );
  }

  const sorted = [...data].sort((a, b) => b.count - a.count).slice(0, 10);

  return (
    <div className="h-56">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={sorted}
          layout="vertical"
          margin={{ top: 0, right: 12, bottom: 0, left: 0 }}
        >
          <XAxis
            type="number"
            tick={{ fontSize: 10, fill: "var(--color-fg-tertiary)" }}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            type="category"
            dataKey="tag"
            tick={{ fontSize: 10, fill: "var(--color-fg-secondary)" }}
            tickLine={false}
            axisLine={false}
            width={100}
          />
          <Tooltip content={<BarTooltip />} />
          <Bar dataKey="count" radius={[0, 4, 4, 0]} animationDuration={600}>
            {sorted.map((_, i) => (
              <Cell key={i} fill={TAG_BAR_COLORS[i % TAG_BAR_COLORS.length]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ─── PARA Distribution Donut ────────────────────────────────
function ParaDistributionChart({ data }: { data: ParaCount[] }) {
  if (data.length === 0) {
    return (
      <p className="text-xs text-[var(--color-fg-tertiary)] text-center py-8">
        No PARA data available.
      </p>
    );
  }

  const total = data.reduce((sum, d) => sum + d.count, 0);

  return (
    <div className="flex flex-col items-center">
      <div className="h-48 w-48">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              dataKey="count"
              nameKey="category"
              innerRadius={50}
              outerRadius={75}
              paddingAngle={2}
              animationDuration={600}
            >
              {data.map((entry) => (
                <Cell
                  key={entry.category}
                  fill={PARA_COLORS[entry.category] ?? PARA_COLORS.unclassified}
                />
              ))}
            </Pie>
            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload || payload.length === 0) return null;
                const item = payload[0];
                return (
                  <div className="rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] px-3 py-2 shadow-md">
                    <p className="text-xs font-medium text-[var(--color-fg-primary)] capitalize">
                      {String(item.name)}: {String(item.value)}
                    </p>
                  </div>
                );
              }}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
      {/* Legend */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 mt-2">
        {data.map((item) => {
          const pct = total > 0 ? Math.round((item.count / total) * 100) : 0;
          return (
            <div key={item.category} className="flex items-center gap-1.5">
              <span
                className="inline-block h-2 w-2 rounded-full"
                style={{
                  backgroundColor: PARA_COLORS[item.category] ?? PARA_COLORS.unclassified,
                }}
              />
              <span className="text-xs text-[var(--color-fg-secondary)] capitalize">
                {item.category}: {pct}%
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Main Trends Component ──────────────────────────────────
export function DiaryTrends({ className }: DiaryTrendsProps) {
  const [timeRange, setTimeRange] = useState<TimeRange>(30);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["episodeStats", timeRange],
    queryFn: () => getEpisodeStats(timeRange),
    staleTime: 60_000,
  });

  if (isLoading) return <DiaryTrendsSkeleton />;

  if (isError) {
    return (
      <div className={cn("space-y-4", className)}>
        <p className="text-sm text-[var(--color-fg-secondary)]">
          Unable to load trends. Try refreshing.
        </p>
      </div>
    );
  }

  return (
    <div className={cn("space-y-6", className)}>
      {/* Time range toggle */}
      <div className="flex items-center gap-1 rounded-[var(--radius-md)] bg-[var(--color-bg-overlay)] p-1 w-fit">
        {TIME_RANGES.map((range) => (
          <button
            key={range}
            onClick={() => setTimeRange(range)}
            className={cn(
              "px-3 py-1 text-xs font-medium rounded-[var(--radius-sm)] transition-colors cursor-pointer",
              timeRange === range
                ? "bg-[var(--color-bg-surface)] text-[var(--color-fg-primary)] shadow-sm"
                : "text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-secondary)]",
            )}
          >
            {range}d
          </button>
        ))}
      </div>

      {/* Mood & Energy chart */}
      <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)]">
        <div className="border-b border-[var(--color-border-subtle)] px-4 py-3">
          <h3 className="text-sm font-semibold text-[var(--color-fg-primary)]">Mood & Energy</h3>
        </div>
        <div className="p-4">
          <MoodEnergyChart data={data?.moodTrend ?? []} />
          {/* Legend */}
          <div className="flex items-center gap-4 mt-2 px-1">
            <div className="flex items-center gap-1.5">
              <span className="inline-block h-0.5 w-4 rounded-full bg-[var(--color-agent-diary)]" />
              <span className="text-xs text-[var(--color-fg-tertiary)]">Mood</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="inline-block h-0.5 w-4 rounded-full bg-[var(--color-success-500)]" />
              <span className="text-xs text-[var(--color-fg-tertiary)]">Energy</span>
            </div>
          </div>
        </div>
      </div>

      {/* Two-column charts */}
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        {/* Tag frequency */}
        <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)]">
          <div className="border-b border-[var(--color-border-subtle)] px-4 py-3">
            <h3 className="text-sm font-semibold text-[var(--color-fg-primary)]">Tag Frequency</h3>
          </div>
          <div className="p-4">
            <TagFrequencyChart data={data?.tagFrequency ?? []} />
          </div>
        </div>

        {/* PARA distribution */}
        <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)]">
          <div className="border-b border-[var(--color-border-subtle)] px-4 py-3">
            <h3 className="text-sm font-semibold text-[var(--color-fg-primary)]">
              PARA Distribution
            </h3>
          </div>
          <div className="p-4">
            <ParaDistributionChart data={data?.paraDistribution ?? []} />
          </div>
        </div>
      </div>

      {/* Stats summary */}
      {data && (
        <div className="flex flex-wrap gap-4 text-xs text-[var(--color-fg-secondary)]">
          <span>
            Total entries:{" "}
            <strong className="text-[var(--color-fg-primary)]">{data.totalEntries}</strong>
          </span>
          {data.averageMood != null && (
            <span>
              Avg mood:{" "}
              <strong className="text-[var(--color-fg-primary)]">
                {data.averageMood.toFixed(1)}
              </strong>
            </span>
          )}
          {data.averageEnergy != null && (
            <span>
              Avg energy:{" "}
              <strong className="text-[var(--color-fg-primary)]">
                {data.averageEnergy.toFixed(1)}
              </strong>
            </span>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Skeleton ───────────────────────────────────────────────
function DiaryTrendsSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-8 w-40" />
      <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)]">
        <div className="border-b border-[var(--color-border-subtle)] px-4 py-3">
          <Skeleton className="h-4 w-32" />
        </div>
        <div className="p-4">
          <Skeleton className="h-64 w-full" />
        </div>
      </div>
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-4">
          <Skeleton className="h-56 w-full" />
        </div>
        <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-4">
          <Skeleton className="h-48 w-48 rounded-full mx-auto" />
        </div>
      </div>
    </div>
  );
}

export { DiaryTrendsSkeleton };

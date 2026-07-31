import { useQuery } from "@tanstack/react-query";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import { format, parseISO } from "date-fns";
import { getMoodEnergyTrends } from "@/api/dashboard";
import type { MoodEnergyPoint } from "@/api/dashboard";
import { Skeleton } from "@/components/ui/skeleton";

interface MoodChartProps {
  days?: number;
}

function CustomTooltip({
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
        {format(parseISO(label), "EEE d MMM")}
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

export function MoodChart({ days = 30 }: MoodChartProps) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["moodEnergyTrends", days],
    queryFn: () => getMoodEnergyTrends(days),
    staleTime: 60_000,
  });

  if (isLoading) return <MoodChartSkeleton />;

  if (isError) {
    return (
      <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-4">
        <h3 className="text-sm font-semibold text-[var(--color-fg-primary)] mb-2">
          Mood & Energy Trends
        </h3>
        <p className="text-xs text-[var(--color-fg-secondary)]">Unable to load trend data.</p>
      </div>
    );
  }

  const chartData =
    data?.map((point: MoodEnergyPoint) => ({
      ...point,
      dateLabel: point.date,
    })) ?? [];

  const moodColor = "var(--color-agent-diary)";
  const energyColor = "var(--color-agent-memory)";

  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)]">
      <div className="flex items-center justify-between border-b border-[var(--color-border-subtle)] px-4 py-3">
        <h3 className="text-sm font-semibold text-[var(--color-fg-primary)]">
          Mood & Energy Trends
        </h3>
        <span className="text-xs text-[var(--color-fg-tertiary)]">{days} days</span>
      </div>
      <div className="p-4">
        {chartData.length === 0 ? (
          <p className="text-xs text-[var(--color-fg-tertiary)] text-center py-8">
            No diary entries yet. Start capturing your thoughts.
          </p>
        ) : (
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
                <defs>
                  <linearGradient id="gradMood" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={moodColor} stopOpacity={0.25} />
                    <stop offset="95%" stopColor={moodColor} stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="gradEnergy" x1="0" y1="0" x2="0" y2="1">
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
                  dataKey="dateLabel"
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
                  interval={Math.max(0, Math.floor(chartData.length / 6))}
                />
                <YAxis
                  domain={[0, 10]}
                  tick={{ fontSize: 10, fill: "var(--color-fg-tertiary)" }}
                  tickLine={false}
                  axisLine={false}
                  ticks={[0, 2, 4, 6, 8, 10]}
                />
                <Tooltip content={<CustomTooltip />} />
                <Area
                  type="monotone"
                  dataKey="mood"
                  name="Mood"
                  stroke={moodColor}
                  strokeWidth={2}
                  fill="url(#gradMood)"
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
                  fill="url(#gradEnergy)"
                  dot={false}
                  connectNulls
                  animationDuration={600}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* Legend */}
        {chartData.length > 0 && (
          <div className="flex items-center gap-4 mt-2 px-1">
            <div className="flex items-center gap-1.5">
              <span
                className="inline-block h-0.5 w-4 rounded-full"
                style={{ backgroundColor: moodColor }}
              />
              <span className="text-xs text-[var(--color-fg-tertiary)]">Mood</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span
                className="inline-block h-0.5 w-4 rounded-full"
                style={{
                  backgroundColor: energyColor,
                  backgroundImage:
                    "repeating-linear-gradient(90deg, transparent, transparent 3px, var(--color-bg-surface) 3px, var(--color-bg-surface) 5px)",
                }}
              />
              <span className="text-xs text-[var(--color-fg-tertiary)]">Energy</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function MoodChartSkeleton() {
  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)]">
      <div className="flex items-center justify-between border-b border-[var(--color-border-subtle)] px-4 py-3">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-3 w-12" />
      </div>
      <div className="p-4">
        <Skeleton className="h-56 w-full" />
      </div>
    </div>
  );
}

export { MoodChartSkeleton };

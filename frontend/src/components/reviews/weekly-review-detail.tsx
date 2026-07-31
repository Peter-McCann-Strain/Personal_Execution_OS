import {
  AlertTriangle,
  ArrowDown,
  ArrowRight,
  ArrowUp,
  Battery,
  CheckCircle2,
  Lightbulb,
  ListChecks,
  Quote,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { normalizeProgressPercent } from "@/lib/utils";
import type { WeeklyReview } from "@/types";

// ─── Section Header ─────────────────────────────────────────

function SectionHeader({ icon, title }: { icon: React.ReactNode; title: string }) {
  return (
    <div className="mb-4 flex items-center gap-2 border-b border-[var(--color-border-subtle)] pb-2">
      <span className="text-[var(--color-fg-tertiary)]">{icon}</span>
      <h3 className="text-xs font-semibold uppercase tracking-widest text-[var(--color-fg-tertiary)]">
        {title}
      </h3>
    </div>
  );
}

// ─── Mood Trend Arrow ───────────────────────────────────────

function MoodTrendArrow({
  current,
  previous,
}: {
  current: number | null;
  previous?: number | null;
}) {
  if (current == null || previous == null) {
    return <ArrowRight className="h-5 w-5 text-[var(--color-fg-disabled)]" />;
  }
  const diff = current - previous;
  if (diff > 0)
    return (
      <span className="flex items-center gap-1 text-[var(--color-success-500)]">
        <ArrowUp className="h-5 w-5" />
        <span className="text-sm font-medium">from {previous.toFixed(1)}</span>
      </span>
    );
  if (diff < 0)
    return (
      <span className="flex items-center gap-1 text-[var(--color-error-500)]">
        <ArrowDown className="h-5 w-5" />
        <span className="text-sm font-medium">from {previous.toFixed(1)}</span>
      </span>
    );
  return <ArrowRight className="h-5 w-5 text-[var(--color-fg-disabled)]" />;
}

// ─── Accomplishments ────────────────────────────────────────

function AccomplishmentsSection({ items }: { items: string[] }) {
  return (
    <section>
      <SectionHeader icon={<CheckCircle2 className="h-4 w-4" />} title="Accomplishments" />
      <ul className="space-y-2">
        {items.map((item, idx) => (
          <li key={idx} className="flex items-start gap-2">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-success-500)]" />
            <span className="text-sm text-[var(--color-fg-primary)]">{item}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

// ─── Mood Chart ─────────────────────────────────────────────

interface MoodChartData {
  day: string;
  mood: number;
  energy: number;
}

function MoodEnergyChart({ data }: { data: MoodChartData[] }) {
  return (
    <section>
      <SectionHeader icon={<TrendingUp className="h-4 w-4" />} title="Mood & Energy" />
      <div className="grid gap-4 md:grid-cols-2">
        {/* Mood chart */}
        <Card variant="elevated" padding="sm">
          <h4 className="mb-2 text-xs font-medium text-[var(--color-fg-tertiary)]">Mood (7-day)</h4>
          <ResponsiveContainer width="100%" height={160}>
            <AreaChart data={data}>
              <defs>
                <linearGradient id="moodGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="var(--color-info-500)" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="var(--color-info-500)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-subtle)" />
              <XAxis
                dataKey="day"
                tick={{ fontSize: 10, fill: "var(--color-fg-tertiary)" }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                domain={[0, 10]}
                tick={{ fontSize: 10, fill: "var(--color-fg-tertiary)" }}
                axisLine={false}
                tickLine={false}
                width={24}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "var(--color-bg-surface)",
                  border: "1px solid var(--color-border-default)",
                  borderRadius: "var(--radius-md)",
                  fontSize: 12,
                  color: "var(--color-fg-primary)",
                }}
              />
              <Area
                type="monotone"
                dataKey="mood"
                stroke="var(--color-info-500)"
                fill="url(#moodGradient)"
                strokeWidth={2}
              />
            </AreaChart>
          </ResponsiveContainer>
        </Card>

        {/* Energy chart */}
        <Card variant="elevated" padding="sm">
          <h4 className="mb-2 text-xs font-medium text-[var(--color-fg-tertiary)]">
            Energy (7-day)
          </h4>
          <ResponsiveContainer width="100%" height={160}>
            <AreaChart data={data}>
              <defs>
                <linearGradient id="energyGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="var(--color-success-500)" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="var(--color-success-500)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-subtle)" />
              <XAxis
                dataKey="day"
                tick={{ fontSize: 10, fill: "var(--color-fg-tertiary)" }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                domain={[0, 10]}
                tick={{ fontSize: 10, fill: "var(--color-fg-tertiary)" }}
                axisLine={false}
                tickLine={false}
                width={24}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "var(--color-bg-surface)",
                  border: "1px solid var(--color-border-default)",
                  borderRadius: "var(--radius-md)",
                  fontSize: 12,
                  color: "var(--color-fg-primary)",
                }}
              />
              <Area
                type="monotone"
                dataKey="energy"
                stroke="var(--color-success-500)"
                fill="url(#energyGradient)"
                strokeWidth={2}
              />
            </AreaChart>
          </ResponsiveContainer>
        </Card>
      </div>
    </section>
  );
}

// ─── Goal Progress Section ──────────────────────────────────

function GoalProgressSection({
  goals,
}: {
  goals: Array<{ title: string; progress: number; status: string }>;
}) {
  if (goals.length === 0) return null;

  return (
    <section>
      <SectionHeader icon={<TrendingUp className="h-4 w-4" />} title="Goal Progress" />
      <div className="space-y-3">
        {goals.map((goal, idx) => (
          <Card key={idx} variant="elevated" padding="sm">
            <div className="mb-1.5 flex items-center justify-between">
              <span className="text-sm font-medium text-[var(--color-fg-primary)]">
                {goal.title}
              </span>
              <Badge
                variant={
                  goal.status === "on_track" || goal.status === "active"
                    ? "success"
                    : goal.status === "at_risk"
                      ? "warning"
                      : "default"
                }
                size="sm"
              >
                {goal.status.replace("_", " ")}
              </Badge>
            </div>
            <div className="flex items-center gap-2">
              {(() => {
                const progress = normalizeProgressPercent(goal.progress);
                return (
                  <>
                    <Progress
                      value={progress}
                      colorVariant={
                        progress >= 75
                          ? "success"
                          : progress >= 50
                            ? "default"
                            : progress >= 25
                              ? "warning"
                              : "error"
                      }
                      className="h-1.5 flex-1"
                    />
                    <span className="font-mono text-xs text-[var(--color-fg-tertiary)]">
                      {Math.round(progress)}%
                    </span>
                  </>
                );
              })()}
            </div>
          </Card>
        ))}
      </div>
    </section>
  );
}

// ─── Open Commitments ───────────────────────────────────────

function OpenCommitmentsSection({
  commitments,
}: {
  commitments: Array<{ action: string; status: string }>;
}) {
  if (commitments.length === 0) return null;

  return (
    <section>
      <SectionHeader icon={<ListChecks className="h-4 w-4" />} title="Open Commitments" />
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--color-border-subtle)]">
              <th className="pb-2 text-left text-xs font-medium text-[var(--color-fg-tertiary)]">
                Action
              </th>
              <th className="pb-2 text-right text-xs font-medium text-[var(--color-fg-tertiary)]">
                Status
              </th>
            </tr>
          </thead>
          <tbody>
            {commitments.map((c, idx) => (
              <tr
                key={idx}
                className="border-b border-[var(--color-border-subtle)] last:border-b-0"
              >
                <td className="py-2 text-[var(--color-fg-primary)]">{c.action}</td>
                <td className="py-2 text-right">
                  <Badge
                    variant={
                      c.status === "completed"
                        ? "success"
                        : c.status === "overdue" || c.status === "OVERDUE"
                          ? "error"
                          : c.status === "at_risk"
                            ? "warning"
                            : "default"
                    }
                    size="sm"
                  >
                    {c.status}
                  </Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// ─── Patterns Detected ──────────────────────────────────────

const patternIcons: Record<string, React.ReactNode> = {
  productivity: <TrendingUp className="h-4 w-4" />,
  energy: <Battery className="h-4 w-4" />,
  avoidance: <AlertTriangle className="h-4 w-4" />,
};

function PatternsSection({ patterns }: { patterns: string[] }) {
  if (patterns.length === 0) return null;

  return (
    <section>
      <SectionHeader icon={<Sparkles className="h-4 w-4" />} title="Patterns Detected" />
      <div className="space-y-3">
        {patterns.map((pattern, idx) => {
          const lowered = pattern.toLowerCase();
          const icon = patternIcons[
            Object.keys(patternIcons).find((k) => lowered.includes(k)) ?? ""
          ] ?? <Lightbulb className="h-4 w-4" />;

          return (
            <Card
              key={idx}
              variant="elevated"
              padding="sm"
              className="border-l-2 border-l-[var(--color-info-500)]"
            >
              <div className="flex items-start gap-2">
                <span className="mt-0.5 shrink-0 text-[var(--color-info-500)]">{icon}</span>
                <p className="text-sm text-[var(--color-fg-secondary)]">{pattern}</p>
              </div>
            </Card>
          );
        })}
      </div>
    </section>
  );
}

// ─── Recommendations ────────────────────────────────────────

function RecommendationsSection({ recommendations }: { recommendations: string[] }) {
  if (recommendations.length === 0) return null;

  return (
    <section>
      <SectionHeader icon={<Lightbulb className="h-4 w-4" />} title="Recommendations" />
      <ol className="space-y-2">
        {recommendations.map((rec, idx) => (
          <li key={idx} className="flex items-start gap-3">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--color-bg-overlay)] font-mono text-xs font-bold text-[var(--color-fg-secondary)]">
              {idx + 1}
            </span>
            <span className="text-sm text-[var(--color-fg-primary)]">{rec}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

// ─── Key Insight ────────────────────────────────────────────

function KeyInsightSection({ insight }: { insight: string | null }) {
  if (!insight) return null;

  return (
    <section>
      <Card
        padding="lg"
        className="border-[var(--color-info-500)]/30 bg-gradient-to-r from-[var(--color-info-50)] to-[var(--color-bg-surface)]"
      >
        <div className="flex items-start gap-3">
          <Quote className="mt-1 h-6 w-6 shrink-0 text-[var(--color-info-500)]" />
          <p className="text-base leading-relaxed text-[var(--color-fg-primary)] italic">
            &ldquo;{insight}&rdquo;
          </p>
        </div>
      </Card>
    </section>
  );
}

// ─── Weekly Review Detail ───────────────────────────────────

interface WeeklyReviewDetailProps {
  review: WeeklyReview;
  previousMood?: number | null;
  moodChartData?: MoodChartData[];
}

function WeeklyReviewDetail({ review, previousMood, moodChartData = [] }: WeeklyReviewDetailProps) {
  return (
    <div className="space-y-8">
      {/* Header */}
      <header>
        <h1 className="mb-1 text-2xl font-bold text-[var(--color-fg-primary)]">
          Weekly Review: {review.period}
        </h1>
        {review.average_mood != null && (
          <div className="flex items-center gap-3">
            <span className="text-4xl font-bold text-[var(--color-fg-primary)]">
              {review.average_mood.toFixed(1)}
            </span>
            <div className="flex flex-col">
              <span className="text-xs text-[var(--color-fg-tertiary)]">average mood</span>
              <MoodTrendArrow current={review.average_mood} previous={previousMood} />
            </div>
          </div>
        )}
        {review.mood_summary && (
          <p className="mt-2 text-sm text-[var(--color-fg-secondary)]">{review.mood_summary}</p>
        )}
      </header>

      {/* Accomplishments */}
      {(review.accomplishments ?? []).length > 0 && (
        <AccomplishmentsSection items={review.accomplishments} />
      )}

      {/* Mood & Energy chart */}
      {moodChartData.length > 0 && <MoodEnergyChart data={moodChartData} />}

      {/* Goal Progress */}
      <GoalProgressSection goals={review.goal_progress ?? []} />

      {/* Open Commitments */}
      <OpenCommitmentsSection commitments={review.open_commitments ?? []} />

      {/* Patterns */}
      <PatternsSection patterns={review.patterns_noticed ?? []} />

      {/* Recommendations */}
      <RecommendationsSection recommendations={review.recommendations ?? []} />

      {/* Key Insight */}
      <KeyInsightSection insight={review.key_insight} />
    </div>
  );
}

export { WeeklyReviewDetail };
export type { WeeklyReviewDetailProps, MoodChartData };

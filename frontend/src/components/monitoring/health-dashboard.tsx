import { useState } from "react";
import {
  Database,
  Server,
  Brain,
  Sparkles,
  Calendar,
  Mail,
  Search,
  Activity,
  Send,
  RefreshCw,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { cn, formatRelativeTime } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { getHealth } from "@/api/monitoring";
import type { HealthServiceState } from "@/types";

// ─── Service Config ─────────────────────────────────────────

interface ServiceConfig {
  key: string;
  label: string;
  icon: LucideIcon;
}

const serviceConfigs: ServiceConfig[] = [
  { key: "database", label: "PostgreSQL", icon: Database },
  { key: "redis", label: "Redis", icon: Server },
  { key: "ollama", label: "Ollama", icon: Brain },
  { key: "anthropic", label: "Claude", icon: Sparkles },
  { key: "google_calendar", label: "Google Calendar", icon: Calendar },
  { key: "gmail", label: "Gmail", icon: Mail },
  { key: "tavily", label: "Tavily", icon: Search },
  { key: "posthog", label: "PostHog", icon: Activity },
  { key: "sentry", label: "Sentry", icon: Activity },
  { key: "telegram", label: "Telegram", icon: Send },
];

// ─── Status Colors ──────────────────────────────────────────

const statusColorMap: Record<string, string> = {
  ok: "bg-[var(--color-success-500)]",
  degraded: "bg-[var(--color-warning-500)]",
  lagging: "bg-[var(--color-warning-500)]",
  down: "bg-[var(--color-error-500)]",
  unknown: "bg-[var(--color-fg-disabled)]",
};

const statusBorderMap: Record<string, string> = {
  ok: "border-[var(--color-success-500)]/30",
  degraded: "border-[var(--color-warning-500)]/30",
  lagging: "border-[var(--color-warning-500)]/30",
  down: "border-[var(--color-error-500)]/30",
  unknown: "border-[var(--color-border-default)]",
};

// ─── HealthDashboard Component ──────────────────────────────

function HealthDashboard() {
  const queryClient = useQueryClient();
  const [checkCooldown, setCheckCooldown] = useState(false);

  const {
    data: health,
    isLoading,
    dataUpdatedAt,
  } = useQuery({
    queryKey: ["health"],
    queryFn: () => getHealth(),
    refetchInterval: 60_000,
  });

  const handleCheckNow = () => {
    setCheckCooldown(true);
    queryClient.invalidateQueries({ queryKey: ["health"] });
    setTimeout(() => setCheckCooldown(false), 5000);
  };

  const overallStatus = health?.status ?? "ok";

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-semibold text-[var(--color-fg-primary)]">System Status</h2>
          <OverallStatusBadge status={overallStatus} />
        </div>
        <div className="flex items-center gap-3">
          {dataUpdatedAt > 0 && (
            <span className="text-xs text-[var(--color-fg-tertiary)]">
              Last check: {formatRelativeTime(new Date(dataUpdatedAt))}
            </span>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={handleCheckNow}
            disabled={checkCooldown || isLoading}
            loading={isLoading}
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Check Now
          </Button>
        </div>
      </div>

      {/* Service Grid */}
      {isLoading ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {Array.from({ length: serviceConfigs.length }).map((_, i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {serviceConfigs.map((svc) => {
            const svcStatus = health?.services?.[svc.key];
            const status = svcStatus?.status ?? "unknown";
            const message = svcStatus?.message ?? "Not configured";
            return (
              <ServiceStatusCard
                key={svc.key}
                label={svc.label}
                icon={svc.icon}
                status={status}
                message={message}
              />
            );
          })}
        </div>
      )}

      {/* Legend */}
      <div className="flex items-center gap-4 text-xs text-[var(--color-fg-tertiary)]">
        <div className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full bg-[var(--color-success-500)]" />
          OK
        </div>
        <div className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full bg-[var(--color-error-500)]" />
          Error
        </div>
        <div className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full bg-[var(--color-warning-500)]" />
          Warning
        </div>
        <div className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full bg-[var(--color-fg-disabled)]" />
          Not Configured
        </div>
      </div>
    </div>
  );
}

// ─── ServiceStatusCard ──────────────────────────────────────

interface ServiceStatusCardProps {
  label: string;
  icon: LucideIcon;
  status: HealthServiceState;
  message: string;
}

function ServiceStatusCard({ label, icon: Icon, status, message }: ServiceStatusCardProps) {
  return (
    <Card padding="md" className={cn("relative border transition-colors", statusBorderMap[status])}>
      {/* Status dot */}
      <span
        className={cn(
          "absolute top-3 right-3 h-2.5 w-2.5 rounded-full",
          statusColorMap[status],
          (status === "down" || status === "degraded") && "animate-pulse",
        )}
      />

      <div className="flex flex-col gap-2">
        <Icon className="h-5 w-5 text-[var(--color-fg-secondary)]" />
        <p className="text-sm font-semibold text-[var(--color-fg-primary)]">{label}</p>
        <p className="text-xs text-[var(--color-fg-tertiary)] line-clamp-2">{message}</p>
      </div>
    </Card>
  );
}

// ─── OverallStatusBadge ─────────────────────────────────────

function OverallStatusBadge({ status }: { status: "ok" | "degraded" | "down" }) {
  const variant = status === "ok" ? "success" : status === "degraded" ? "warning" : "error";

  const label = status === "ok" ? "Healthy" : status === "degraded" ? "Degraded" : "Down";

  return (
    <Badge variant={variant} size="md">
      {label}
    </Badge>
  );
}

export { HealthDashboard };

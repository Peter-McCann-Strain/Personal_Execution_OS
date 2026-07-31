import type { VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";
import { AGENT_COLORS } from "@/lib/agent-utils";
import { badgeVariants } from "./badge-variants";
import type { AgentName, ParaCategory, Priority } from "@/types";

interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, size, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant, size, className }))} {...props} />;
}

// --- Agent Badge ---

interface AgentBadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  agent: AgentName;
  size?: "sm" | "md";
}

function AgentBadge({ agent, size = "md", className, ...props }: AgentBadgeProps) {
  const color = AGENT_COLORS[agent];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 font-medium whitespace-nowrap rounded-[var(--radius-full)] border border-[var(--color-border-default)]",
        size === "sm" ? "px-1.5 py-0.5 text-[10px] leading-tight" : "px-2 py-0.5 text-xs",
        className,
      )}
      style={{ color, borderColor: `color-mix(in oklch, ${color} 30%, transparent)` }}
      {...props}
    >
      <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ backgroundColor: color }} />
      {agent}
    </span>
  );
}

// --- Priority Badge ---

const priorityVariantMap: Record<Priority, "error" | "warning" | "info" | "default"> = {
  P0: "error",
  P1: "warning",
  P2: "info",
  P3: "default",
};

interface PriorityBadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  priority: Priority;
  size?: "sm" | "md";
}

function PriorityBadge({ priority, size = "md", className, ...props }: PriorityBadgeProps) {
  return (
    <Badge variant={priorityVariantMap[priority]} size={size} className={className} {...props}>
      {priority}
    </Badge>
  );
}

// --- PARA Badge ---

const paraVariantMap: Record<ParaCategory, "info" | "success" | "warning" | "default"> = {
  project: "info",
  area: "success",
  resource: "warning",
  archive: "default",
};

interface ParaBadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  category: ParaCategory;
  size?: "sm" | "md";
}

function ParaBadge({ category, size = "md", className, ...props }: ParaBadgeProps) {
  return (
    <Badge
      variant={paraVariantMap[category]}
      size={size}
      className={cn("capitalize", className)}
      {...props}
    >
      {category}
    </Badge>
  );
}

export { Badge, AgentBadge, PriorityBadge, ParaBadge };
export type { BadgeProps, AgentBadgeProps, PriorityBadgeProps, ParaBadgeProps };

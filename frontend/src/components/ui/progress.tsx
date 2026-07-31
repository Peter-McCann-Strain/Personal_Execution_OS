import * as React from "react";
import * as ProgressPrimitive from "@radix-ui/react-progress";
import { cn } from "@/lib/utils";
import type { AgentName } from "@/types";

const colorMap: Record<string, string> = {
  default: "bg-[var(--color-info-500)]",
  success: "bg-[var(--color-success-500)]",
  warning: "bg-[var(--color-warning-500)]",
  error: "bg-[var(--color-error-500)]",
  diary: "bg-[var(--color-agent-diary)]",
  memory: "bg-[var(--color-agent-memory)]",
  research: "bg-[var(--color-agent-research)]",
  review: "bg-[var(--color-agent-review)]",
  project: "bg-[var(--color-agent-project)]",
  communications: "bg-[var(--color-agent-comms)]",
  tools: "bg-[var(--color-agent-tools)]",
  notification: "bg-[var(--color-agent-notif)]",
  save: "bg-[var(--color-agent-memory)]",
  plan_day: "bg-[var(--color-agent-project)]",
  socratic: "bg-[var(--color-agent-socratic)]",
};

interface ProgressProps extends React.ComponentPropsWithoutRef<typeof ProgressPrimitive.Root> {
  colorVariant?: "default" | "success" | "warning" | "error" | AgentName;
}

const Progress = React.forwardRef<React.ComponentRef<typeof ProgressPrimitive.Root>, ProgressProps>(
  (
    { className, value, colorVariant = "default", "aria-label": ariaLabel = "Progress", ...props },
    ref,
  ) => {
    const fillColor = colorMap[colorVariant] ?? colorMap.default;

    return (
      <ProgressPrimitive.Root
        ref={ref}
        value={value ?? 0}
        aria-label={ariaLabel}
        className={cn(
          "relative h-2 w-full overflow-hidden rounded-[var(--radius-full)] bg-[var(--color-bg-overlay)]",
          className,
        )}
        {...props}
      >
        <ProgressPrimitive.Indicator
          className={cn(
            "h-full rounded-[var(--radius-full)] transition-all duration-500 ease-out",
            fillColor,
          )}
          style={{ width: `${value ?? 0}%` }}
        />
      </ProgressPrimitive.Root>
    );
  },
);
Progress.displayName = "Progress";

export { Progress };
export type { ProgressProps };

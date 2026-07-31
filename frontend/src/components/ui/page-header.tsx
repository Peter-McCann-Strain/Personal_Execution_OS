import type { LucideIcon } from "lucide-react";
import type { AgentName } from "@/types";
import { AGENT_COLORS } from "@/lib/agent-utils";

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  icon?: LucideIcon;
  agentColor?: AgentName;
  children?: React.ReactNode;
}

function PageHeader({ title, subtitle, icon: Icon, agentColor, children }: PageHeaderProps) {
  const accentColor = agentColor ? AGENT_COLORS[agentColor] : undefined;

  return (
    <div className="flex items-start justify-between gap-4">
      <div className="flex items-center gap-3">
        {Icon && (
          <div
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[var(--radius-lg)]"
            style={
              accentColor
                ? { backgroundColor: `color-mix(in oklch, ${accentColor} 15%, transparent)` }
                : { backgroundColor: "var(--color-bg-overlay)" }
            }
          >
            <Icon
              className="h-5 w-5"
              style={accentColor ? { color: accentColor } : { color: "var(--color-fg-secondary)" }}
            />
          </div>
        )}
        <div>
          <h1
            className="text-xl font-bold tracking-tight text-[var(--color-fg-primary)]"
            style={
              accentColor
                ? {
                    borderBottom: `2px solid ${accentColor}`,
                    paddingBottom: "2px",
                    display: "inline-block",
                  }
                : undefined
            }
          >
            {title}
          </h1>
          {subtitle && (
            <p className="mt-0.5 text-sm text-[var(--color-fg-secondary)]">{subtitle}</p>
          )}
        </div>
      </div>
      {children && <div className="flex items-center gap-2 shrink-0">{children}</div>}
    </div>
  );
}

export { PageHeader };
export type { PageHeaderProps };

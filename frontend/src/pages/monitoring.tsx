import { useState } from "react";
import { Gauge } from "lucide-react";
import { PageHeader } from "@/components/ui/page-header";
import { PageTransition } from "@/components/ui/page-transition";
import * as Tabs from "@radix-ui/react-tabs";
import { cn } from "@/lib/utils";
import { HealthDashboard } from "@/components/monitoring/health-dashboard";
import { LLMAnalytics } from "@/components/monitoring/llm-analytics";
import { AgentActivityLog } from "@/components/monitoring/agent-activity-log";
import { AgentComparison } from "@/components/monitoring/agent-comparison";
import { ContextInspector } from "@/components/monitoring/context-inspector";
import { ReleaseReadiness } from "@/components/monitoring/release-readiness";
import { RuntimeObserver } from "@/components/monitoring/runtime-observer";

// ─── Tab Config ─────────────────────────────────────────────

const tabs = [
  { value: "health", label: "System Health" },
  { value: "runtime", label: "Runtime" },
  { value: "readiness", label: "Readiness" },
  { value: "context", label: "Context" },
  { value: "llm", label: "LLM Analytics" },
  { value: "activity", label: "Agent Activity" },
  { value: "agents", label: "Agent Comparison" },
] as const;

type TabValue = (typeof tabs)[number]["value"];

// ─── MonitoringPage Component ───────────────────────────────

function MonitoringPage() {
  const [activeTab, setActiveTab] = useState<TabValue>("health");

  return (
    <PageTransition>
      <div className="flex flex-col gap-6 p-6">
        {/* Header */}
        <PageHeader title="System Monitoring" subtitle="Agent performance and costs" icon={Gauge} />

        {/* Tabs */}
        <Tabs.Root value={activeTab} onValueChange={(v) => setActiveTab(v as TabValue)}>
          <Tabs.List className="flex items-center gap-1 border-b border-[var(--color-border-default)]">
            {tabs.map((tab) => (
              <Tabs.Trigger
                key={tab.value}
                value={tab.value}
                className={cn(
                  "relative px-4 py-2.5 text-sm font-medium transition-colors",
                  "text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-secondary)]",
                  "data-[state=active]:text-[var(--color-fg-primary)]",
                  "after:absolute after:bottom-0 after:left-0 after:right-0 after:h-0.5 after:transition-colors",
                  "data-[state=active]:after:bg-[var(--color-info-500)]",
                  "after:bg-transparent",
                )}
              >
                {tab.label}
              </Tabs.Trigger>
            ))}
          </Tabs.List>

          <div className="mt-6">
            <Tabs.Content value="health">
              <HealthDashboard />
            </Tabs.Content>

            <Tabs.Content value="runtime">
              <RuntimeObserver />
            </Tabs.Content>

            <Tabs.Content value="readiness">
              <ReleaseReadiness />
            </Tabs.Content>

            <Tabs.Content value="context">
              <ContextInspector />
            </Tabs.Content>

            <Tabs.Content value="llm">
              <LLMAnalytics />
            </Tabs.Content>

            <Tabs.Content value="activity">
              <AgentActivityLog />
            </Tabs.Content>

            <Tabs.Content value="agents">
              <AgentComparison />
            </Tabs.Content>
          </div>
        </Tabs.Root>
      </div>
    </PageTransition>
  );
}

export { MonitoringPage };

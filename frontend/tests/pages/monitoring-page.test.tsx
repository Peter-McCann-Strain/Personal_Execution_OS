import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent } from "../test-utils";
import { MonitoringPage } from "@/pages/monitoring";

vi.mock("@/components/ui/page-transition", () => ({
  PageTransition: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/components/ui/page-header", () => ({
  PageHeader: ({ title, subtitle }: { title: string; subtitle: string }) => (
    <div>
      <h1>{title}</h1>
      <p>{subtitle}</p>
    </div>
  ),
}));

vi.mock("@/components/monitoring/health-dashboard", () => ({
  HealthDashboard: () => <div>Health Dashboard Panel</div>,
}));

vi.mock("@/components/monitoring/runtime-observer", () => ({
  RuntimeObserver: () => <div>Runtime Observer Panel</div>,
}));

vi.mock("@/components/monitoring/release-readiness", () => ({
  ReleaseReadiness: () => <div>Release Readiness Panel</div>,
}));

vi.mock("@/components/monitoring/context-inspector", () => ({
  ContextInspector: () => <div>Context Inspector Panel</div>,
}));

vi.mock("@/components/monitoring/llm-analytics", () => ({
  LLMAnalytics: () => <div>LLM Analytics Panel</div>,
}));

vi.mock("@/components/monitoring/agent-activity-log", () => ({
  AgentActivityLog: () => <div>Agent Activity Panel</div>,
}));

vi.mock("@/components/monitoring/agent-comparison", () => ({
  AgentComparison: () => <div>Agent Comparison Panel</div>,
}));

describe("MonitoringPage", () => {
  it("renders the page header and switches between monitoring tabs", async () => {
    const user = userEvent.setup();

    renderWithProviders(<MonitoringPage />);

    expect(screen.getByRole("heading", { name: "System Monitoring" })).toBeInTheDocument();
    expect(screen.getByText("Agent performance and costs")).toBeInTheDocument();
    expect(screen.getByText("Health Dashboard Panel")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Runtime" }));
    expect(screen.getByText("Runtime Observer Panel")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Readiness" }));
    expect(screen.getByText("Release Readiness Panel")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Context" }));
    expect(screen.getByText("Context Inspector Panel")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "LLM Analytics" }));
    expect(screen.getByText("LLM Analytics Panel")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Agent Activity" }));
    expect(screen.getByText("Agent Activity Panel")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Agent Comparison" }));
    expect(screen.getByText("Agent Comparison Panel")).toBeInTheDocument();
  });
});

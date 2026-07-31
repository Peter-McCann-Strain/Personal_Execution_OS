import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen } from "../../test-utils";
import { RecentActivity, RecentActivitySkeleton } from "@/components/dashboard/recent-activity";
import type { AgentAction } from "@/types";

const mocks = vi.hoisted(() => ({
  getRecentAgentActivity: vi.fn(),
}));

vi.mock("@/api/dashboard", () => ({
  getRecentAgentActivity: mocks.getRecentAgentActivity,
}));

vi.mock("@/lib/date", () => ({
  formatActionTime: () => "09:00",
}));

function createAction(overrides: Partial<AgentAction> = {}): AgentAction {
  return {
    id: "action-1",
    agent_name: "review",
    action_type: "summarise",
    model_used: "claude",
    tokens_in: 100,
    tokens_out: 200,
    cost_usd: 0.01,
    duration_ms: 1500,
    input_summary: "Input",
    output_summary: "Reviewed the latest weekly summary and highlighted the top issues.",
    trace_id: "trace-1",
    created_at: "2026-04-07T09:00:00Z",
    ...overrides,
  };
}

describe("RecentActivity", () => {
  beforeEach(() => {
    mocks.getRecentAgentActivity.mockReset();
  });

  it("renders recent activity items and falls back to the action type when no summary is available", async () => {
    mocks.getRecentAgentActivity.mockResolvedValue([
      createAction(),
      createAction({
        id: "action-2",
        agent_name: "tools",
        action_type: "tool_call",
        output_summary: null,
      }),
    ]);

    renderWithProviders(<RecentActivity />);

    expect(await screen.findByText("Agent Activity")).toBeInTheDocument();
    expect(await screen.findAllByText("09:00")).toHaveLength(2);
    expect(screen.getByText(/Reviewed the latest weekly summary/)).toBeInTheDocument();
    expect(screen.getByText("tool_call")).toBeInTheDocument();
  });

  it("renders empty and error states", async () => {
    mocks.getRecentAgentActivity.mockResolvedValueOnce([]);
    const firstRender = renderWithProviders(<RecentActivity />);

    expect(
      await screen.findByText("No agent activity yet. Send a message to get started."),
    ).toBeInTheDocument();
    firstRender.unmount();

    mocks.getRecentAgentActivity.mockRejectedValueOnce(new Error("dashboard failed"));
    renderWithProviders(<RecentActivity />);

    expect(await screen.findByText("Unable to load activity.")).toBeInTheDocument();
  });

  it("renders the loading skeleton", () => {
    const { container } = renderWithProviders(<RecentActivitySkeleton />);

    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });
});

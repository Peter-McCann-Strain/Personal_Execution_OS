import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent, waitFor } from "../../test-utils";
import { AgentComparison } from "@/components/monitoring/agent-comparison";

vi.mock("recharts", async () => {
  const { rechartsMock } = await import("../../recharts-mock");
  return rechartsMock;
});

const mocks = vi.hoisted(() => ({
  getAgentComparison: vi.fn(),
}));

vi.mock("@/api/monitoring", () => ({
  getAgentComparison: mocks.getAgentComparison,
}));

describe("AgentComparison", () => {
  beforeEach(() => {
    mocks.getAgentComparison.mockReset();
  });

  it("renders the loading state, the usage breakdown, and period switching", async () => {
    const user = userEvent.setup();
    mocks.getAgentComparison.mockImplementation((period: "today" | "7d" | "30d") =>
      Promise.resolve(
        period === "30d"
          ? {
              summaries: [
                {
                  agent: "research",
                  call_count: 7,
                  avg_cost: 0.0123,
                  avg_latency_ms: 1450,
                  error_rate: 1.5,
                  total_tokens: 4800,
                },
                {
                  agent: "mystery",
                  call_count: 1,
                  avg_cost: 0,
                  avg_latency_ms: 75,
                  error_rate: 0,
                  total_tokens: 42,
                },
              ],
              usage_distribution: [
                { agent: "research", calls: 7 },
                { agent: "tools", calls: 3 },
                { agent: "mystery", calls: 1 },
              ],
            }
          : {
              summaries: [
                {
                  agent: "diary",
                  call_count: 12,
                  avg_cost: 0.0345,
                  avg_latency_ms: 2400,
                  error_rate: 6.2,
                  total_tokens: 12345,
                },
                {
                  agent: "memory",
                  call_count: 3,
                  avg_cost: 0.0042,
                  avg_latency_ms: 800,
                  error_rate: 3.4,
                  total_tokens: 2345,
                },
              ],
              usage_distribution: [
                { agent: "diary", calls: 12 },
                { agent: "memory", calls: 3 },
                { agent: "mystery", calls: 1 },
              ],
            },
      ),
    );

    const { container } = renderWithProviders(<AgentComparison />);

    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);

    expect(await screen.findByText("Agent Performance Comparison")).toBeInTheDocument();
    expect(screen.getByText("Usage Distribution")).toBeInTheDocument();
    expect(screen.getByText("16 total calls")).toBeInTheDocument();
    expect(screen.getByText("Agent Summary")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "30 Days" }));

    await waitFor(() => expect(mocks.getAgentComparison).toHaveBeenLastCalledWith("30d"));
    expect(screen.getByText("11 total calls")).toBeInTheDocument();
  });

  it("renders the empty-state branches when no comparison data is available", async () => {
    mocks.getAgentComparison.mockResolvedValue({
      summaries: [],
      usage_distribution: [],
    });

    renderWithProviders(<AgentComparison />);

    await waitFor(() => expect(screen.getAllByText("No data available")).toHaveLength(2));
  });

  it("falls back to empty states when the comparison query fails", async () => {
    mocks.getAgentComparison.mockRejectedValue(new Error("comparison failed"));

    renderWithProviders(<AgentComparison />);

    await waitFor(() => expect(screen.getAllByText("No data available")).toHaveLength(2));
  });
});

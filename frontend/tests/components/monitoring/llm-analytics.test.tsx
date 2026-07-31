import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent, waitFor } from "../../test-utils";
import { LLMAnalytics } from "@/components/monitoring/llm-analytics";

vi.mock("recharts", async () => {
  const { rechartsMock } = await import("../../recharts-mock");
  return {
    ...rechartsMock,
    Tooltip: (props: Record<string, unknown>) => {
      const formatter = props.formatter as
        ((value: unknown, name?: string, entry?: unknown) => unknown) | undefined;
      formatter?.(undefined, "value", { value: undefined, name: "value" });
      return rechartsMock.Tooltip(props);
    },
  };
});

const mocks = vi.hoisted(() => ({
  invalidateQueries: vi.fn(),
  getLLMStats: vi.fn(),
}));

vi.mock("@tanstack/react-query", async () => {
  const actual =
    await vi.importActual<typeof import("@tanstack/react-query")>("@tanstack/react-query");
  return {
    ...actual,
    useQueryClient: () => ({ invalidateQueries: mocks.invalidateQueries }),
  };
});

vi.mock("@/api/monitoring", () => ({
  getLLMStats: mocks.getLLMStats,
}));

describe("LLMAnalytics", () => {
  beforeEach(() => {
    mocks.invalidateQueries.mockReset();
    mocks.getLLMStats.mockReset();
  });

  it("renders charts, token totals, and refresh behavior", async () => {
    const user = userEvent.setup();
    mocks.getLLMStats.mockImplementation((period: "today" | "7d" | "30d") =>
      Promise.resolve(
        period === "30d"
          ? {
              cost: { today: 1.2345, week: 8.7654, month: 12.3456 },
              cost_trend: [
                { date: "2026-04-01", cost: 0.3 },
                { date: "2026-04-02", cost: 0.45 },
              ],
              cost_by_model: [
                { model: "opus", cost: 3.21 },
                { model: "custom-model", cost: 1.11 },
              ],
              cost_by_agent: [
                { agent: "review", cost: 2.5 },
                { agent: "socratic", cost: 1.2 },
              ],
              tokens: { input: 5200, output: 3100 },
              latency_by_agent: [
                { agent: "review", avg_ms: 3400 },
                { agent: "socratic", avg_ms: 1800 },
              ],
            }
          : {
              cost: { today: 0.1234, week: 1.2345, month: 9.8765 },
              cost_trend: [
                { date: "2026-04-05", cost: 0.12 },
                { date: "2026-04-06", cost: 0.34 },
              ],
              cost_by_model: [
                { model: "haiku", cost: 0.8 },
                { model: "sonnet", cost: 0.4 },
              ],
              cost_by_agent: [
                { agent: "tools", cost: 0.5 },
                { agent: "memory", cost: 0.2 },
              ],
              tokens: { input: 1200, output: 800 },
              latency_by_agent: [
                { agent: "tools", avg_ms: 1200 },
                { agent: "memory", avg_ms: 900 },
              ],
            },
      ),
    );

    const { container } = renderWithProviders(<LLMAnalytics />);

    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);

    expect(await screen.findByText("Cost Trend")).toBeInTheDocument();
    expect(screen.getByText("$0.1234")).toBeInTheDocument();
    expect(screen.getByText("$1.2345")).toBeInTheDocument();
    expect(screen.getByText("$9.8765")).toBeInTheDocument();
    expect(screen.getByText("Input: 1.2K")).toBeInTheDocument();
    expect(screen.getByText("Output: 800")).toBeInTheDocument();

    const refreshButton = screen.getByRole("button", { name: "Refresh analytics" });
    await user.click(refreshButton);
    expect(mocks.invalidateQueries).toHaveBeenCalledWith({ queryKey: ["llm-stats"] });

    await user.click(screen.getByRole("tab", { name: "30 Days" }));
    await waitFor(() => expect(mocks.getLLMStats).toHaveBeenLastCalledWith("30d"));
    expect(screen.getByText("$1.2345")).toBeInTheDocument();
  });

  it("renders fallback colors for unknown models and agents", async () => {
    mocks.getLLMStats.mockResolvedValue({
      cost: { today: 0, week: 0, month: 0 },
      cost_trend: [],
      cost_by_model: [{ model: "experimental-model", cost: 0.5 }],
      cost_by_agent: [{ agent: "unknown-agent", cost: 1.25 }],
      tokens: { input: 0, output: 0 },
      latency_by_agent: [{ agent: "unknown-agent", avg_ms: 100 }],
    });

    renderWithProviders(<LLMAnalytics />);

    expect(await screen.findByText("Cost by Model")).toBeInTheDocument();
    expect(screen.getByText("Cost by Agent")).toBeInTheDocument();
    expect(screen.getByText("Token Usage (Input vs Output)")).toBeInTheDocument();
    expect(screen.getByText("Avg Latency by Agent")).toBeInTheDocument();
    expect(screen.getByText("Input: 0")).toBeInTheDocument();
    expect(screen.getByText("Output: 0")).toBeInTheDocument();
    expect(screen.getAllByTestId("recharts-cell").length).toBeGreaterThan(0);
  });

  it("falls back to zeroed analytics when the query fails", async () => {
    mocks.getLLMStats.mockRejectedValue(new Error("stats unavailable"));

    renderWithProviders(<LLMAnalytics />);

    expect(await screen.findByText("Cost Trend")).toBeInTheDocument();
    expect(screen.getAllByText("$0.0000")).toHaveLength(3);
    expect(screen.getByText("Input: 0")).toBeInTheDocument();
    expect(screen.getByText("Output: 0")).toBeInTheDocument();
    expect(screen.getAllByTestId("recharts-cell")).toHaveLength(2);
  });
});

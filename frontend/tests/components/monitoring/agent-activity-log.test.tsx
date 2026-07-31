import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent } from "@testing-library/react";
import { renderWithProviders, screen, waitFor } from "../../test-utils";
import { AgentActivityLog } from "@/components/monitoring/agent-activity-log";

const mocks = vi.hoisted(() => ({
  getAgentActions: vi.fn(),
  clipboardWriteText: vi.fn(),
  toastSuccess: vi.fn(),
}));

vi.mock("@/api/monitoring", () => ({
  getAgentActions: mocks.getAgentActions,
}));

vi.mock("sonner", () => ({
  toast: {
    success: mocks.toastSuccess,
  },
}));

const activityData = {
  items: [
    {
      id: "action-1",
      agent_name: "diary",
      action_type: "create_entry",
      model_used: "claude-3-haiku-20240307",
      tokens_in: 120,
      tokens_out: 30,
      cost_usd: 0.04,
      duration_ms: 2500,
      trace_id: "trace-a1",
      input_summary: "input one",
      output_summary: "output one",
      created_at: "2026-04-07T09:00:00Z",
    },
    {
      id: "action-2",
      agent_name: "research",
      action_type: "search",
      model_used: "claude-3-sonnet-20240229",
      tokens_in: 0,
      tokens_out: 0,
      cost_usd: 0.08,
      duration_ms: 3500,
      trace_id: null,
      input_summary: null,
      output_summary: null,
      created_at: "2026-04-07T09:15:00Z",
    },
    {
      id: "action-3",
      agent_name: "tools",
      action_type: "approve",
      model_used: "claude-3-opus-20240229",
      tokens_in: 512,
      tokens_out: 128,
      cost_usd: 0.2,
      duration_ms: 6000,
      trace_id: "trace-a3",
      input_summary: "tool input",
      output_summary: "tool output",
      created_at: "2026-04-07T09:30:00Z",
    },
    {
      id: "action-4",
      agent_name: "project",
      action_type: "plan",
      model_used: "custom-model-very-long-name",
      tokens_in: 10,
      tokens_out: 20,
      cost_usd: null,
      duration_ms: null,
      trace_id: null,
      input_summary: null,
      output_summary: "partial output only",
      created_at: "2026-04-07T09:45:00Z",
    },
  ],
  total: 26,
};

describe("AgentActivityLog", () => {
  beforeEach(() => {
    mocks.getAgentActions.mockReset();
    mocks.toastSuccess.mockReset();
    mocks.clipboardWriteText.mockReset();
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: mocks.clipboardWriteText },
      configurable: true,
    });
  });

  it("renders loading and empty states when no activity is present", async () => {
    mocks.getAgentActions.mockResolvedValueOnce({ items: [], total: 0 });

    const { container } = renderWithProviders(<AgentActivityLog />);

    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
    expect(await screen.findByText("No activity found")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Next page" })).not.toBeInTheDocument();
  });

  it("renders activity rows, expansion details, and query-driven filters", async () => {
    mocks.getAgentActions.mockResolvedValue(activityData);

    renderWithProviders(<AgentActivityLog />);

    expect(await screen.findByText("Agent Activity Log")).toBeInTheDocument();
    expect(await screen.findByText("Haiku")).toBeInTheDocument();
    expect(
      screen.getByText(
        (_, element) =>
          element?.tagName === "SPAN" &&
          (element.textContent?.includes("Showing 1-25 of 26") ?? false),
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/custom-mod/)).toBeInTheDocument();
    expect(screen.getByText("Page 1 of 2")).toBeInTheDocument();

    fireEvent.click(screen.getByText("create_entry"));
    expect(screen.getByText("Input (120 tokens)")).toBeInTheDocument();
    expect(screen.getByText("Output (30 tokens)")).toBeInTheDocument();
    expect(screen.getByText("Trace ID:")).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "Copy" })[0]);
    expect(mocks.clipboardWriteText).toHaveBeenCalledWith("input one");
    expect(mocks.toastSuccess).toHaveBeenCalledWith("Copied to clipboard");
    fireEvent.click(screen.getAllByRole("button", { name: "Copy" })[1]);
    expect(mocks.clipboardWriteText).toHaveBeenCalledWith("output one");
    expect(mocks.toastSuccess).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByTitle("trace-a1"));

    const selects = screen.getAllByRole("combobox");
    fireEvent.change(selects[0], { target: { value: "research" } });
    fireEvent.change(selects[1], { target: { value: "sonnet" } });
    fireEvent.change(selects[2], { target: { value: "slowest" } });

    await waitFor(() =>
      expect(mocks.getAgentActions).toHaveBeenLastCalledWith(
        expect.objectContaining({
          limit: 25,
          offset: 0,
          agent: "research",
          model: "sonnet",
          sort: "slowest",
        }),
      ),
    );

    expect(await screen.findByRole("button", { name: "Next page" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() =>
      expect(mocks.getAgentActions).toHaveBeenLastCalledWith(
        expect.objectContaining({
          limit: 25,
          offset: 25,
          agent: "research",
          model: "sonnet",
          sort: "slowest",
        }),
      ),
    );
  });

  it("renders rows without optional summaries or trace ids and copies expanded text", async () => {
    mocks.getAgentActions.mockResolvedValue({
      items: [
        {
          id: "action-5",
          agent_name: "tools",
          action_type: "audit",
          model_used: "experimental-model",
          tokens_in: 8,
          tokens_out: 4,
          cost_usd: 0,
          duration_ms: 0,
          trace_id: null,
          input_summary: null,
          output_summary: null,
          created_at: "2026-04-07T10:00:00Z",
        },
      ],
      total: 1,
    });

    renderWithProviders(<AgentActivityLog />);

    expect(await screen.findByText("Agent Activity Log")).toBeInTheDocument();
    expect(await screen.findByText("audit")).toBeInTheDocument();

    fireEvent.click(screen.getByText("audit"));
    expect(screen.queryByText("Copy")).not.toBeInTheDocument();
    expect(screen.queryByText("Trace ID:")).not.toBeInTheDocument();
  });
});

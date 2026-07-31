import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen } from "../../test-utils";
import { RuntimeObserver } from "@/components/monitoring/runtime-observer";

const mocks = vi.hoisted(() => ({
  getTraceSummaries: vi.fn(),
  getEvalOutcomes: vi.fn(),
  getChannelMetrics: vi.fn(),
  getTelegramWebhookStatus: vi.fn(),
  getSecurityMetrics: vi.fn(),
}));

vi.mock("@/api/monitoring", () => ({
  getTraceSummaries: mocks.getTraceSummaries,
  getEvalOutcomes: mocks.getEvalOutcomes,
  getChannelMetrics: mocks.getChannelMetrics,
  getTelegramWebhookStatus: mocks.getTelegramWebhookStatus,
  getSecurityMetrics: mocks.getSecurityMetrics,
}));

describe("RuntimeObserver", () => {
  beforeEach(() => {
    mocks.getTraceSummaries.mockResolvedValue([
      {
        trace_id: "trace-1234567890",
        channel: "telegram",
        specialist: "tools",
        status: "degraded",
        span_count: 6,
        total_latency_ms: 420,
        error_count: 1,
        created_at: "2026-04-09T09:00:00Z",
      },
    ]);
    mocks.getEvalOutcomes.mockResolvedValue([
      {
        id: "eval-1",
        trace_id: "trace-1234567890",
        response_id: "resp-1",
        specialist: "tools",
        source: "telegram",
        eval_status: "auto_scored",
        quality_scores: { final_response_quality: 0.92 },
        channel_metrics: { chunk_count: 2 },
        feedback_rating: "thumbs_up",
        created_at: "2026-04-09T09:00:00Z",
      },
    ]);
    mocks.getChannelMetrics.mockResolvedValue([
      {
        source: "telegram",
        interaction_count: 12,
        avg_latency_ms: 180.5,
        avg_chunk_count: 1.75,
        render_failures: 1,
        delivery_failures: 2,
        delivery_success_rate: 0.833,
        avg_retry_count: 0.25,
        total_retry_count: 3,
        chunked_delivery_rate: 0.4,
        reply_anchor_drop_rate: 0.1,
        feedback_callback_success_rate: 0.5,
      },
    ]);
    mocks.getTelegramWebhookStatus.mockResolvedValue({
      status: "degraded",
      url: "https://example.com/webhook",
      pending_update_count: 3,
      last_error_date: null,
      last_error_message: "temporary flood control",
      max_connections: 40,
      last_error_age_seconds: null,
      webhook_lagging: true,
      pending_updates_warning_threshold: 10,
    });
    mocks.getSecurityMetrics.mockResolvedValue({
      generated_at: "2026-04-09T09:00:00Z",
      policy_decision_count: 6,
      tool_receipt_count: 8,
      instruction_risk_decisions: 1,
      trust_boundary_denies: 1,
      confirmation_required_count: 2,
      confirmation_allowed_count: 2,
      confirmation_denied_count: 0,
      confirmation_coverage: 1,
      mutating_receipt_count: 3,
      mutating_without_confirmation_count: 1,
      failed_mutating_receipt_count: 0,
      suspicious_tool_receipt_count: 1,
      duplicate_idempotency_key_count: 1,
      policy_counts: { tool_confirmation: 2 },
      decision_counts: { allow: 2, deny: 1 },
    });
  });

  it("renders runtime traces, channel metrics, evals, webhook state, and security signals", async () => {
    renderWithProviders(<RuntimeObserver />);

    expect((await screen.findAllByText("tools · telegram")).length).toBeGreaterThan(0);
    expect(screen.getByText(/Trace: trace-12345/)).toBeInTheDocument();
    expect(screen.getByText("Latency: 420 ms")).toBeInTheDocument();
    expect(
      screen.getByText("12 interactions · 1.75 avg chunks · 0.25 avg retries"),
    ).toBeInTheDocument();
    expect(screen.getByText("2 delivery failures")).toBeInTheDocument();
    expect(screen.getByText("Final response quality: 0.92")).toBeInTheDocument();
    expect(screen.getByText("Last error: temporary flood control")).toBeInTheDocument();
    expect(screen.getByText("Instruction-risk decisions: 1")).toBeInTheDocument();
    expect(screen.getByText("Mutations without confirmation: 1")).toBeInTheDocument();
    expect(screen.queryByText("Voice Reflection Ops")).not.toBeInTheDocument();
  });
});

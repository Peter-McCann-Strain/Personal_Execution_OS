import { beforeEach, describe, it, expect, vi } from "vitest";
import { renderWithProviders, screen } from "../../test-utils";
import { ReleaseReadiness } from "@/components/monitoring/release-readiness";

const mocks = vi.hoisted(() => ({
  getAssistantNativeEvalSummary: vi.fn().mockResolvedValue({
    generated_at: "2026-04-13T09:00:00Z",
    dataset_id: "assistant_native_continuity.v1",
    version: "v1",
    dataset_path: "data/evaluation/datasets/assistant_native_continuity.v1.json",
    passing: true,
    case_count: 6,
    pass_count: 6,
    pass_rate: 1,
    baseline_pass_count: 1,
    baseline_pass_rate: 0.1667,
    baseline_lift: 0.8333,
    minimum_pass_rate_target: 1,
    minimum_baseline_lift_target: 0.5,
    minimum_case_count_target: 6,
    failing_case_ids: [],
    asset_errors: [],
    cases: [],
  }),
  getAssistantNativeMetrics: vi.fn().mockResolvedValue({
    generated_at: "2026-04-07T09:00:00Z",
    interaction_sample_size: 12,
    continuity_resolution_count: 4,
    continuity_retry_replayed_count: 2,
    continuity_duplicate_prevented_count: 1,
    continuity_note_reference_resolved_count: 1,
    assistant_receipt_count: 6,
    pending_action_cleared_count: 3,
    project_draft_created_interaction_count: 2,
    project_drafts_total: 5,
    project_drafts_applied: 3,
    notes_total: 42,
    daily_notes_total: 7,
    moc_notes_total: 4,
    canvases_total: 2,
    note_links_total: 30,
    wiki_links_total: 10,
    manual_links_total: 8,
    semantic_links_total: 12,
    content_assets_total: 6,
    content_assets_ready_total: 2,
    content_assets_in_progress_total: 1,
    content_assets_needs_review_total: 2,
    content_assets_done_total: 1,
    notebooklm_podcast_total: 4,
  }),
  getPreflightReport: vi.fn().mockResolvedValue({
    status: "fail",
    generated_at: "2026-04-07T09:00:00Z",
    checks: [
      {
        name: "provider_configuration",
        status: "ok",
        message: "Required provider configuration is present",
        required: true,
        details: {
          required: {
            anthropic: true,
            database: true,
            redis: true,
            chat_api: true,
          },
          optional: {
            google_workspace: false,
            tavily: true,
            telegram: false,
            sentry: true,
            posthog: true,
          },
          missing_required: [],
          missing_optional: ["google_workspace", "telegram"],
        },
      },
      {
        name: "evaluation_assets",
        status: "ok",
        message: "Evaluation assets are present",
        required: true,
        details: { root: "data/evaluation" },
      },
      {
        name: "optional_integrations",
        status: "warn",
        message: "Some optional integrations are unavailable",
        required: false,
        details: { missing_servers: ["google-calendar"] },
      },
      {
        name: "critical_backend",
        status: "fail",
        message: "A required backend dependency is offline",
        required: true,
        details: { service: "postgres" },
      },
      {
        name: "staged_feature",
        status: "skipped",
        message: "A non-essential feature was intentionally skipped",
        required: false,
        details: {},
      },
    ],
  }),
  getPromptVersions: vi.fn().mockResolvedValue([
    {
      kind: "supervisor",
      agent: "routing",
      prompt_version: "v1",
      prompt_source: "src/app/agents/prompts/routing.py",
      model_policy: "claude-haiku",
      eval_rubric_id: null,
      memory_namespace: null,
      confirmation_policy: null,
      allowed_tool_patterns: [],
    },
    {
      kind: "specialist",
      agent: "tools",
      prompt_version: "v1",
      prompt_source: "src/app/agents/prompts/tools.py",
      model_policy: "claude-sonnet",
      eval_rubric_id: "tools-execution-v1",
      memory_namespace: "tools.session",
      confirmation_policy: "on_mutation",
      allowed_tool_patterns: ["google-calendar__*"],
    },
    {
      kind: "specialist",
      agent: "socratic",
      prompt_version: null,
      prompt_source: "src/app/agents/socratic/prompts",
      model_policy: "claude-sonnet",
      eval_rubric_id: "socratic-tutorial-v1",
      memory_namespace: "tutorial.socratic",
      confirmation_policy: "never",
      allowed_tool_patterns: [],
    },
  ]),
}));

vi.mock("@/api/monitoring", () => ({
  getAssistantNativeEvalSummary: mocks.getAssistantNativeEvalSummary,
  getAssistantNativeMetrics: mocks.getAssistantNativeMetrics,
  getPreflightReport: mocks.getPreflightReport,
  getPromptVersions: mocks.getPromptVersions,
}));

describe("ReleaseReadiness", () => {
  beforeEach(() => {
    mocks.getAssistantNativeEvalSummary.mockReset();
    mocks.getAssistantNativeMetrics.mockReset();
    mocks.getPreflightReport.mockReset();
    mocks.getPromptVersions.mockReset();

    mocks.getAssistantNativeEvalSummary.mockResolvedValue({
      generated_at: "2026-04-13T09:00:00Z",
      dataset_id: "assistant_native_continuity.v1",
      version: "v1",
      dataset_path: "data/evaluation/datasets/assistant_native_continuity.v1.json",
      passing: true,
      case_count: 6,
      pass_count: 6,
      pass_rate: 1,
      baseline_pass_count: 1,
      baseline_pass_rate: 0.1667,
      baseline_lift: 0.8333,
      minimum_pass_rate_target: 1,
      minimum_baseline_lift_target: 0.5,
      minimum_case_count_target: 6,
      failing_case_ids: [],
      asset_errors: [],
      cases: [],
    });

    mocks.getAssistantNativeMetrics.mockResolvedValue({
      generated_at: "2026-04-07T09:00:00Z",
      interaction_sample_size: 12,
      continuity_resolution_count: 4,
      continuity_retry_replayed_count: 2,
      continuity_duplicate_prevented_count: 1,
      continuity_note_reference_resolved_count: 1,
      assistant_receipt_count: 6,
      pending_action_cleared_count: 3,
      project_draft_created_interaction_count: 2,
      project_drafts_total: 5,
      project_drafts_applied: 3,
      notes_total: 42,
      daily_notes_total: 7,
      moc_notes_total: 4,
      canvases_total: 2,
      note_links_total: 30,
      wiki_links_total: 10,
      manual_links_total: 8,
      semantic_links_total: 12,
      content_assets_total: 6,
      content_assets_ready_total: 2,
      content_assets_in_progress_total: 1,
      content_assets_needs_review_total: 2,
      content_assets_done_total: 1,
      notebooklm_podcast_total: 4,
    });

    mocks.getPreflightReport.mockResolvedValue({
      status: "fail",
      generated_at: "2026-04-07T09:00:00Z",
      checks: [
        {
          name: "provider_configuration",
          status: "ok",
          message: "Required provider configuration is present",
          required: true,
          details: {
            required: {
              anthropic: true,
              database: true,
              redis: true,
              chat_api: true,
            },
            optional: {
              google_workspace: false,
              tavily: true,
              telegram: false,
              sentry: true,
              posthog: true,
            },
            missing_required: [],
            missing_optional: ["google_workspace", "telegram"],
          },
        },
        {
          name: "evaluation_assets",
          status: "ok",
          message: "Evaluation assets are present",
          required: true,
          details: { root: "data/evaluation" },
        },
        {
          name: "optional_integrations",
          status: "warn",
          message: "Some optional integrations are unavailable",
          required: false,
          details: { missing_servers: ["google-calendar"] },
        },
        {
          name: "critical_backend",
          status: "fail",
          message: "A required backend dependency is offline",
          required: true,
          details: { service: "postgres" },
        },
        {
          name: "staged_feature",
          status: "skipped",
          message: "A non-essential feature was intentionally skipped",
          required: false,
          details: {},
        },
      ],
    });

    mocks.getPromptVersions.mockResolvedValue([
      {
        kind: "supervisor",
        agent: "routing",
        prompt_version: "v1",
        prompt_source: "src/app/agents/prompts/routing.py",
        model_policy: "claude-haiku",
        eval_rubric_id: null,
        memory_namespace: null,
        confirmation_policy: null,
        allowed_tool_patterns: [],
      },
      {
        kind: "specialist",
        agent: "tools",
        prompt_version: "v1",
        prompt_source: "src/app/agents/prompts/tools.py",
        model_policy: "claude-sonnet",
        eval_rubric_id: "tools-execution-v1",
        memory_namespace: "tools.session",
        confirmation_policy: "on_mutation",
        allowed_tool_patterns: ["google-calendar__*"],
      },
      {
        kind: "specialist",
        agent: "socratic",
        prompt_version: null,
        prompt_source: "src/app/agents/socratic/prompts",
        model_policy: "claude-sonnet",
        eval_rubric_id: "socratic-tutorial-v1",
        memory_namespace: "tutorial.socratic",
        confirmation_policy: "never",
        allowed_tool_patterns: [],
      },
    ]);
  });

  it("shows loading skeletons while readiness data is pending", () => {
    mocks.getPreflightReport.mockImplementationOnce(() => new Promise(() => undefined));
    mocks.getPromptVersions.mockImplementationOnce(() => new Promise(() => undefined));
    mocks.getAssistantNativeEvalSummary.mockImplementationOnce(() => new Promise(() => undefined));
    mocks.getAssistantNativeMetrics.mockImplementationOnce(() => new Promise(() => undefined));

    const { container } = renderWithProviders(<ReleaseReadiness />);

    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });

  it("renders preflight and prompt governance data", async () => {
    renderWithProviders(<ReleaseReadiness />);

    expect(await screen.findByText("Preflight Checks")).toBeInTheDocument();
    expect(screen.getByText("Prompt Governance")).toBeInTheDocument();
    expect(await screen.findByText("provider configuration")).toBeInTheDocument();
    expect(screen.getByText("Required Providers")).toBeInTheDocument();
    expect(screen.getByText("Optional Integrations")).toBeInTheDocument();
    expect(screen.getByText("anthropic: configured")).toBeInTheDocument();
    expect(screen.getByText("google workspace: not attached")).toBeInTheDocument();
    expect(await screen.findByText("evaluation assets")).toBeInTheDocument();
    expect(screen.getByText("optional integrations")).toBeInTheDocument();
    expect(screen.getByText("critical backend")).toBeInTheDocument();
    expect(screen.getByText("staged feature")).toBeInTheDocument();
    expect(screen.getByText("routing")).toBeInTheDocument();
    expect(screen.getByText("tools")).toBeInTheDocument();
    expect(screen.getByText("socratic")).toBeInTheDocument();
    expect(screen.getByText("1 runtime surfaces still unversioned")).toBeInTheDocument();
    expect(
      screen.getByText("Agents with tool or confirmation policy boundaries"),
    ).toBeInTheDocument();
    expect(screen.getByText("Assistant Receipts")).toBeInTheDocument();
    expect(screen.getAllByText("Continuity Replays")).toHaveLength(2);
    expect(screen.getByText("Continuity Runtime")).toBeInTheDocument();
    expect(screen.getByText("Knowledge System")).toBeInTheDocument();
    expect(screen.getByText("Content Factory")).toBeInTheDocument();
    expect(screen.getByText("Resolutions")).toBeInTheDocument();
    expect(screen.getByText("NotebookLM queued")).toBeInTheDocument();
    expect(screen.getByText("Baseline lift")).toBeInTheDocument();
  });

  it("surfaces errors from preflight and prompt governance queries", async () => {
    mocks.getPreflightReport.mockRejectedValueOnce(new Error("preflight failed"));
    mocks.getPromptVersions.mockRejectedValueOnce(new Error("prompt versions failed"));
    mocks.getAssistantNativeEvalSummary.mockRejectedValueOnce(
      new Error("assistant native replays failed"),
    );
    mocks.getAssistantNativeMetrics.mockRejectedValueOnce(new Error("assistant native failed"));

    renderWithProviders(<ReleaseReadiness />);

    expect(await screen.findByText("preflight failed")).toBeInTheDocument();
    expect(screen.getByText("prompt versions failed")).toBeInTheDocument();
    expect(screen.getAllByText("assistant native failed")).toHaveLength(4);
    expect(screen.getByText("assistant native replays failed")).toBeInTheDocument();
  });
});

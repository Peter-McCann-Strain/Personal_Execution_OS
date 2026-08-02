"""Tests for the monitoring API routes — actions list, LLM stats, agent comparison."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from src.app.api.deps import get_db
from src.app.api.routes.monitoring import router
from src.app.core.exceptions import EXCEPTION_STATUS_MAP, AppError, ErrorResponse, NotFoundError
from tests.unit.api.auth_helpers import override_current_principal

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


async def _mock_get_db():
    yield AsyncMock()


def _build_app(*, override_auth: bool = True) -> FastAPI:
    app = FastAPI()
    app.dependency_overrides[get_db] = _mock_get_db

    if override_auth:
        override_current_principal(app)

    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        status_code, error_code = EXCEPTION_STATUS_MAP.get(type(exc), (500, "app_error"))
        body = ErrorResponse(error=error_code, message=str(exc))
        return JSONResponse(status_code=status_code, content=body.model_dump())

    app.include_router(router, prefix="/api")
    return app


def _make_mock_action(
    *,
    agent_name: str = "diary",
    cost_usd: float = 0.001,
    duration_ms: int = 500,
) -> MagicMock:
    now = datetime.now(UTC)
    m = MagicMock()
    m.id = uuid.uuid4()
    m.agent_name = agent_name
    m.action_type = "process"
    m.model_used = "claude-haiku"
    m.tokens_in = 100
    m.tokens_out = 200
    m.cost_usd = cost_usd
    m.duration_ms = duration_ms
    m.input_summary = "Input"
    m.output_summary = "Output"
    m.trace_id = "trace-123"
    m.created_at = now
    return m


# ---------------------------------------------------------------------------
# list_agent_actions
# ---------------------------------------------------------------------------


async def test_list_actions_success():
    """GET /monitoring/actions returns paginated actions."""
    mock_action = _make_mock_action()

    mock_session = AsyncMock()

    count_result = MagicMock()
    count_result.scalar_one.return_value = 1

    data_result = MagicMock()
    data_result.scalars.return_value.all.return_value = [mock_action]

    mock_session.execute = AsyncMock(side_effect=[count_result, data_result])

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/monitoring/actions")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["agent_name"] == "diary"
    assert data["items"][0]["cost_usd"] == 0.001


async def test_list_actions_with_filters():
    """GET /monitoring/actions with filters is accepted."""
    mock_session = AsyncMock()

    count_result = MagicMock()
    count_result.scalar_one.return_value = 0

    data_result = MagicMock()
    data_result.scalars.return_value.all.return_value = []

    mock_session.execute = AsyncMock(side_effect=[count_result, data_result])

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/monitoring/actions",
            params={"agent": "diary", "model": "claude-haiku", "sort": "costliest"},
        )

    assert resp.status_code == 200
    assert resp.json()["total"] == 0


# ---------------------------------------------------------------------------
# llm_stats
# ---------------------------------------------------------------------------


async def test_llm_stats():
    """GET /monitoring/llm-stats returns cost, token, and latency stats."""
    mock_session = AsyncMock()

    # Build mock results for the 8 execute calls in llm_stats
    # 1) cost today
    cost_today = MagicMock()
    cost_today.scalar_one.return_value = 0.05

    # 2) cost week
    cost_week = MagicMock()
    cost_week.scalar_one.return_value = 0.35

    # 3) cost month
    cost_month = MagicMock()
    cost_month.scalar_one.return_value = 1.20

    # 4) cost trend
    trend_row = MagicMock()
    trend_row.d = "2026-03-15"
    trend_row.cost = 0.05
    cost_trend = MagicMock()
    cost_trend.__iter__ = MagicMock(return_value=iter([trend_row]))

    # 5) cost by model
    model_row = MagicMock()
    model_row.model = "claude-haiku"
    model_row.cost = 0.30
    cost_by_model = MagicMock()
    cost_by_model.__iter__ = MagicMock(return_value=iter([model_row]))

    # 6) cost by agent
    agent_row = MagicMock()
    agent_row.agent = "diary"
    agent_row.cost = 0.20
    cost_by_agent = MagicMock()
    cost_by_agent.__iter__ = MagicMock(return_value=iter([agent_row]))

    # 7) tokens
    token_row = MagicMock()
    token_row.input = 5000
    token_row.output = 8000
    tokens = MagicMock()
    tokens.one.return_value = token_row

    # 8) latency by agent
    latency_row = MagicMock()
    latency_row.agent = "diary"
    latency_row.avg_ms = 450.5
    latency = MagicMock()
    latency.__iter__ = MagicMock(return_value=iter([latency_row]))

    mock_session.execute = AsyncMock(
        side_effect=[
            cost_today,
            cost_week,
            cost_month,
            cost_trend,
            cost_by_model,
            cost_by_agent,
            tokens,
            latency,
        ]
    )

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/monitoring/llm-stats", params={"period": "7d"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["cost"]["today"] == 0.05
    assert data["cost"]["week"] == 0.35
    assert data["cost"]["month"] == 1.20
    assert len(data["cost_trend"]) == 1
    assert len(data["cost_by_model"]) == 1
    assert data["tokens"]["input"] == 5000
    assert data["tokens"]["output"] == 8000


# ---------------------------------------------------------------------------
# agent_comparison
# ---------------------------------------------------------------------------


async def test_agent_comparison():
    """GET /monitoring/agent-comparison returns summaries and distribution."""
    mock_session = AsyncMock()

    # Summary rows
    summary_row = MagicMock()
    summary_row.agent = "diary"
    summary_row.call_count = 42
    summary_row.avg_cost = 0.001
    summary_row.avg_latency_ms = 450.0
    summary_row.error_rate = 0.02
    summary_row.total_tokens = 15000
    summaries = MagicMock()
    summaries.__iter__ = MagicMock(return_value=iter([summary_row]))

    # Usage distribution rows
    usage_row = MagicMock()
    usage_row.agent = "diary"
    usage_row.calls = 42
    usage = MagicMock()
    usage.__iter__ = MagicMock(return_value=iter([usage_row]))

    mock_session.execute = AsyncMock(side_effect=[summaries, usage])

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/monitoring/agent-comparison", params={"period": "30d"})

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["summaries"]) == 1
    assert data["summaries"][0]["agent"] == "diary"
    assert data["summaries"][0]["call_count"] == 42
    assert len(data["usage_distribution"]) == 1
    assert data["usage_distribution"][0]["calls"] == 42


async def test_workflow_shadows():
    """GET /ops/workflow-shadows returns shadow workflow summaries."""
    mock_session = AsyncMock()
    row = MagicMock()
    row.id = uuid.uuid4()
    row.source = "telegram"
    row.specialist = "review"
    row.trace_id = "trace-shadow"
    row.metadata_ = {
        "live_workflow_id": "live-123",
        "live_specialist": "review",
        "shadow_specialist": "review",
        "route_match": True,
        "shadow_status": "completed",
        "executed": True,
        "confidence": 0.91,
        "latency_ms": 142,
        "result_preview": "Shadow review output",
    }
    row.created_at = datetime.now(UTC)

    data_result = MagicMock()
    data_result.scalars.return_value.all.return_value = [row]
    mock_session.execute = AsyncMock(return_value=data_result)

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/ops/workflow-shadows")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["trace_id"] == "trace-shadow"
    assert data[0]["route_match"] is True
    assert data[0]["shadow_status"] == "completed"
    assert data[0]["result_preview"] == "Shadow review output"


async def test_workflow_runtimes():
    """GET /ops/workflow-runtimes returns persisted live runtime outcomes."""
    mock_session = AsyncMock()
    row = MagicMock()
    row.id = uuid.uuid4()
    row.source = "telegram"
    row.specialist = "review"
    row.status = "completed"
    row.trace_id = "trace-live"
    row.response_id = "response-123"
    row.metadata_ = {
        "workflow_runtime": {
            "mode": "live",
            "status": "completed",
            "executed": True,
            "fallback_used": False,
            "latency_ms": 58,
            "response_agent": "review",
            "response_preview": "Live workflow review",
        }
    }
    row.created_at = datetime.now(UTC)

    data_result = MagicMock()
    data_result.scalars.return_value.all.return_value = [row]
    mock_session.execute = AsyncMock(return_value=data_result)

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/ops/workflow-runtimes")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["trace_id"] == "trace-live"
    assert data[0]["runtime_mode"] == "live"
    assert data[0]["runtime_status"] == "completed"
    assert data[0]["executed"] is True
    assert data[0]["response_preview"] == "Live workflow review"


@pytest.mark.asyncio
async def test_security_metrics_aggregates_policy_and_receipt_signals():
    """GET /ops/security-metrics aggregates prompt-injection and mutation safety signals."""
    decisions = [
        SimpleNamespace(policy_name="instruction_like_content", decision="degraded"),
        SimpleNamespace(policy_name="tool_trust_boundary", decision="deny"),
        SimpleNamespace(policy_name="tool_confirmation", decision="require_confirmation"),
        SimpleNamespace(policy_name="tool_confirmation", decision="allow"),
        SimpleNamespace(policy_name="tool_confirmation", decision="deny"),
    ]
    receipts = [
        SimpleNamespace(
            mutation_class="mutating",
            status="executed",
            idempotency_key="idem-1",
            audit_metadata={"confirmation_required": True, "instruction_like_content": True},
        ),
        SimpleNamespace(
            mutation_class="mutating",
            status="failed",
            idempotency_key="idem-2",
            audit_metadata={"confirmation_required": False},
        ),
        SimpleNamespace(
            mutation_class="read_only",
            status="executed",
            idempotency_key="idem-2",
            audit_metadata={},
        ),
    ]

    app = _build_app()
    with (
        patch(
            "src.app.api.routes.monitoring.list_policy_decisions",
            new_callable=AsyncMock,
            return_value=decisions,
        ),
        patch(
            "src.app.api.routes.monitoring.list_tool_receipts",
            new_callable=AsyncMock,
            return_value=receipts,
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/ops/security-metrics")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["policy_decision_count"] == 5
    assert payload["tool_receipt_count"] == 3
    assert payload["instruction_risk_decisions"] == 1
    assert payload["trust_boundary_denies"] == 1
    assert payload["confirmation_required_count"] == 1
    assert payload["confirmation_allowed_count"] == 1
    assert payload["confirmation_denied_count"] == 1
    assert payload["confirmation_coverage"] == 1.0
    assert payload["mutating_receipt_count"] == 2
    assert payload["mutating_without_confirmation_count"] == 1
    assert payload["failed_mutating_receipt_count"] == 1
    assert payload["suspicious_tool_receipt_count"] == 1
    assert payload["duplicate_idempotency_key_count"] == 1
    assert payload["policy_counts"]["tool_confirmation"] == 3
    assert payload["decision_counts"]["deny"] == 2


@pytest.mark.asyncio
async def test_security_metrics_handles_empty_samples():
    """GET /ops/security-metrics returns safe defaults with no records."""
    app = _build_app()
    with (
        patch(
            "src.app.api.routes.monitoring.list_policy_decisions",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.app.api.routes.monitoring.list_tool_receipts",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/ops/security-metrics")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["policy_decision_count"] == 0
    assert payload["tool_receipt_count"] == 0
    assert payload["confirmation_coverage"] is None
    assert payload["policy_counts"] == {}
    assert payload["decision_counts"] == {}


@pytest.mark.asyncio
async def test_assistant_native_metrics_aggregates_workspace_and_continuity_signals():
    """GET /ops/assistant-native-metrics rolls up continuity, drafts, notes, links, and content."""
    mock_session = AsyncMock()

    interactions_result = MagicMock()
    interactions_result.scalars.return_value.all.return_value = [
        {
            "continuity_resolution_type": "retry_pending_action",
            "continuity_retry_replayed": True,
            "continuity_duplicate_prevented": False,
            "continuity_note_reference_resolved": False,
            "assistant_receipt_present": True,
            "pending_action_cleared": True,
            "project_draft_created": True,
        },
        {
            "continuity_resolution_type": "already_completed_action",
            "continuity_retry_replayed": False,
            "continuity_duplicate_prevented": True,
            "continuity_note_reference_resolved": True,
            "assistant_receipt_present": False,
            "pending_action_cleared": False,
            "project_draft_created": False,
        },
    ]

    note_kinds_result = MagicMock()
    note_kinds_result.scalars.return_value.all.return_value = ["daily", "moc", None]

    canvases_result = MagicMock()
    canvases_result.scalars.return_value.all.return_value = [uuid.uuid4(), uuid.uuid4()]

    note_links_result = MagicMock()
    note_links_result.scalars.return_value.all.return_value = [
        "wiki",
        "manual",
        "semantic",
        "semantic",
    ]

    project_drafts_result = MagicMock()
    project_drafts_result.all.return_value = [
        ("draft", None),
        ("applied", uuid.uuid4()),
    ]

    content_assets_result = MagicMock()
    content_assets_result.all.return_value = [
        ("ready", "notebooklm_podcast"),
        ("needs_review", "notebooklm_podcast"),
        ("done", "article"),
    ]

    saved_memories_result = MagicMock()
    saved_memories_result.scalars.return_value.all.return_value = [True, False, True]

    connector_accounts_result = MagicMock()
    connector_accounts_result.scalars.return_value.all.return_value = [uuid.uuid4(), uuid.uuid4()]

    connector_documents_result = MagicMock()
    connector_documents_result.scalars.return_value.all.return_value = [
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
    ]

    scheduled_actions_result = MagicMock()
    scheduled_actions_result.scalars.return_value.all.return_value = [
        "active",
        "paused",
        "active",
    ]

    scheduled_action_runs_result = MagicMock()
    scheduled_action_runs_result.scalars.return_value.all.return_value = [
        uuid.uuid4(),
        uuid.uuid4(),
    ]

    approval_requests_result = MagicMock()
    approval_requests_result.scalars.return_value.all.return_value = [
        "pending",
        "approved",
        "pending",
    ]

    browser_sessions_result = MagicMock()
    browser_sessions_result.scalars.return_value.all.return_value = [uuid.uuid4()]

    mock_session.execute = AsyncMock(
        side_effect=[
            interactions_result,
            note_kinds_result,
            canvases_result,
            note_links_result,
            project_drafts_result,
            content_assets_result,
            saved_memories_result,
            connector_accounts_result,
            connector_documents_result,
            scheduled_actions_result,
            scheduled_action_runs_result,
            approval_requests_result,
            browser_sessions_result,
        ]
    )

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/ops/assistant-native-metrics")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["interaction_sample_size"] == 2
    assert payload["continuity_resolution_count"] == 2
    assert payload["continuity_retry_replayed_count"] == 1
    assert payload["continuity_duplicate_prevented_count"] == 1
    assert payload["assistant_receipt_count"] == 1
    assert payload["project_draft_created_interaction_count"] == 1
    assert payload["project_drafts_total"] == 2
    assert payload["project_drafts_applied"] == 1
    assert payload["notes_total"] == 3
    assert payload["daily_notes_total"] == 1
    assert payload["moc_notes_total"] == 1
    assert payload["canvases_total"] == 2
    assert payload["note_links_total"] == 4
    assert payload["semantic_links_total"] == 2
    assert payload["content_assets_total"] == 3
    assert payload["content_assets_needs_review_total"] == 1
    assert payload["notebooklm_podcast_total"] == 2
    assert payload["saved_memories_total"] == 3
    assert payload["pinned_memories_total"] == 2
    assert payload["connector_accounts_total"] == 2
    assert payload["connector_documents_total"] == 3
    assert payload["scheduled_actions_total"] == 3
    assert payload["scheduled_actions_active_total"] == 2
    assert payload["scheduled_action_runs_total"] == 2
    assert payload["approval_requests_pending_total"] == 2
    assert payload["browser_sessions_total"] == 1


@pytest.mark.asyncio
async def test_assistant_native_evals_reports_replay_summary():
    """GET /ops/assistant-native-evals returns deterministic replay coverage."""
    app = _build_app()

    replay_summary = SimpleNamespace(
        dataset_id="assistant_native_continuity.v1",
        version="v1",
        generated_at=datetime(2026, 4, 13, tzinfo=UTC),
        passing=True,
        case_count=6,
        pass_count=6,
        pass_rate=1.0,
        baseline_pass_count=1,
        baseline_pass_rate=0.1667,
        baseline_lift=0.8333,
        minimum_pass_rate_target=1.0,
        minimum_baseline_lift_target=0.5,
        minimum_case_count_target=6,
        failing_case_ids=[],
        cases=[
            SimpleNamespace(
                id="retry_pending_save_note",
                description="retry pending",
                passed=True,
                baseline_passed=False,
                current_resolution_type="retry_pending_action",
                baseline_resolution_type=None,
                current_forced_specialist="save",
                failures=[],
            )
        ],
    )

    with (
        patch(
            "src.app.api.routes.monitoring.validate_assistant_native_eval_assets",
            return_value=[],
        ),
        patch(
            "src.app.api.routes.monitoring.evaluate_assistant_native_replays",
            return_value=replay_summary,
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/ops/assistant-native-evals")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["passing"] is True
    assert payload["case_count"] == 6
    assert payload["baseline_lift"] == 0.8333
    assert payload["cases"][0]["current_resolution_type"] == "retry_pending_action"


async def test_quality_gates_summarises_runtime_thresholds():
    """GET /ops/quality-gates returns gate metrics and failing flags."""
    mock_session = AsyncMock()

    first_interaction = SimpleNamespace(
        trace_id="trace-1",
        quality_scores={
            "route_quality": 1.0,
            "channel_style": 0.97,
            "final_response_quality": 0.91,
        },
        channel_metrics={"render_passed": True},
    )
    second_interaction = SimpleNamespace(
        trace_id="",
        quality_scores={
            "route_quality": 0.8,
            "channel_style": 0.8,
            "final_response_quality": 0.75,
        },
        channel_metrics={"render_passed": False},
    )

    interactions_result = MagicMock()
    interactions_result.scalars.return_value.all.return_value = [
        first_interaction,
        second_interaction,
    ]

    executed_mutating = SimpleNamespace(
        status="executed",
        mutation_class="mutating",
        audit_metadata={"confirmation_required": True},
    )
    failed_mutating = SimpleNamespace(
        status="failed",
        mutation_class="mutating",
        audit_metadata={"confirmation_required": False},
    )
    tool_receipts_result = MagicMock()
    tool_receipts_result.scalars.return_value.all.return_value = [
        executed_mutating,
        failed_mutating,
    ]

    mock_session.execute = AsyncMock(side_effect=[interactions_result, tool_receipts_result])

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/ops/quality-gates")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["sample_sizes"]["interactions"] == 2
    assert payload["route_accuracy"] == 0.9
    assert payload["tool_execution_success_rate"] == 0.5
    assert payload["confirmation_coverage"] == 0.5
    assert "tool_execution_success_rate" in payload["failing_gates"]
    assert "confirmation_coverage" in payload["failing_gates"]


async def test_prompt_versions():
    """GET /monitoring/prompt-versions returns runtime prompt governance metadata."""
    app = _build_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/monitoring/prompt-versions")

    assert resp.status_code == 200
    data = resp.json()
    assert any(item["agent"] == "routing" for item in data)

    tools_record = next(item for item in data if item["agent"] == "tools")
    assert tools_record["kind"] == "specialist"
    assert tools_record["prompt_version"] == "v1"
    assert tools_record["confirmation_policy"] == "on_mutation"
    assert tools_record["allowed_tool_patterns"]

    socratic_record = next(item for item in data if item["agent"] == "socratic")
    assert socratic_record["prompt_version"] is None
    assert socratic_record["memory_namespace"] == "tutorial.socratic"


@pytest.mark.asyncio
async def test_get_interaction_returns_record():
    """GET /monitoring/interactions/{id} returns a single interaction record."""
    from src.app.api.routes.monitoring import get_interaction

    record = _make_mock_action()
    record.user_id = "user-1"
    record.user_message = "hello"
    record.source = "test"
    record.intent_type = "command"
    record.specialist = "tools"
    record.routing_confidence = 0.9
    record.response_content = "ok"
    record.response_agent = "tools"
    record.duration_ms = 123
    record.eval_status = "passed"
    record.score_relevance = 0.8
    record.score_actionability = 0.7
    record.score_tone = 0.6
    record.score_conciseness = 0.5

    mock_session = AsyncMock()
    with patch(
        "src.app.api.routes.monitoring.repo_get_interaction_by_id",
        new=AsyncMock(return_value=record),
    ) as mock_repo:
        result = await get_interaction(uuid.uuid4(), mock_session)

    assert result.id == str(record.id)
    assert result.user_id == "user-1"
    assert result.score_conciseness == 0.5
    mock_repo.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_interaction_raises_not_found():
    """GET /monitoring/interactions/{id} raises NotFoundError when missing."""
    from src.app.api.routes.monitoring import get_interaction

    mock_session = AsyncMock()
    with (
        patch(
            "src.app.api.routes.monitoring.repo_get_interaction_by_id",
            new=AsyncMock(return_value=None),
        ),
        pytest.raises(NotFoundError, match="Interaction not found"),
    ):
        await get_interaction(uuid.uuid4(), mock_session)


@pytest.mark.asyncio
async def test_quality_scores_rounds_and_handles_null_values():
    """GET /monitoring/quality-scores rounds values and preserves nulls."""
    from src.app.api.routes.monitoring import quality_scores

    mock_session = AsyncMock()
    mock_scores = {
        "relevance": 0.91234,
        "actionability": None,
        "tone": 0.123456,
        "conciseness": None,
        "count": 7,
    }

    with patch(
        "src.app.api.routes.monitoring.repo_get_avg_scores",
        new=AsyncMock(return_value=mock_scores),
    ) as mock_repo:
        result = await quality_scores(
            session=mock_session,
            start=datetime(2026, 4, 1, 0, 0, 0),
            end=datetime(2026, 4, 7, 0, 0, 0),
            specialist="tools",
        )

    assert result.relevance == 0.9123
    assert result.actionability is None
    assert result.tone == 0.1235
    assert result.conciseness is None
    assert result.count == 7
    mock_repo.assert_awaited_once()


async def test_result_adapters_reject_non_callable_and_non_iterable_shapes() -> None:
    from src.app.api.routes.monitoring import _result_rows, _result_scalar_values

    assert await _result_scalar_values(object()) == []
    assert await _result_rows(SimpleNamespace(all="not-callable")) == []

    scalar_result = MagicMock()
    scalar_result.scalars.return_value.all.return_value = 42
    assert await _result_scalar_values(scalar_result) == []

    row_result = MagicMock()
    row_result.all.return_value = None
    assert await _result_rows(row_result) == []


# ---------------------------------------------------------------------------
# _period_to_cutoff — today and unknown-period branches
# ---------------------------------------------------------------------------


async def test_list_actions_with_date_filters():
    """GET /monitoring/actions with date_from and date_to filters exercises lines 166, 168."""
    mock_session = AsyncMock()

    count_result = MagicMock()
    count_result.scalar_one.return_value = 0

    data_result = MagicMock()
    data_result.scalars.return_value.all.return_value = []

    mock_session.execute = AsyncMock(side_effect=[count_result, data_result])

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/monitoring/actions",
            params={"date_from": "2026-01-01", "date_to": "2026-12-31"},
        )

    assert resp.status_code == 200


async def test_llm_stats_period_today():
    """GET /monitoring/llm-stats with period=today exercises _period_to_cutoff 'today' branch."""
    mock_session = AsyncMock()

    # Build 8 mock results for the 8 execute calls
    results = []
    for _ in range(3):
        r = MagicMock()
        r.scalar_one.return_value = 0.0
        results.append(r)
    for _ in range(3):
        r = MagicMock()
        r.__iter__ = MagicMock(return_value=iter([]))
        results.append(r)
    token_row = MagicMock()
    token_row.input = 0
    token_row.output = 0
    tokens = MagicMock()
    tokens.one.return_value = token_row
    results.append(tokens)
    r = MagicMock()
    r.__iter__ = MagicMock(return_value=iter([]))
    results.append(r)

    mock_session.execute = AsyncMock(side_effect=results)

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/monitoring/llm-stats", params={"period": "today"})

    assert resp.status_code == 200


async def test_llm_stats_period_unknown():
    """GET /monitoring/llm-stats with unknown period exercises default branch (line 138)."""
    mock_session = AsyncMock()

    results = []
    for _ in range(3):
        r = MagicMock()
        r.scalar_one.return_value = 0.0
        results.append(r)
    for _ in range(3):
        r = MagicMock()
        r.__iter__ = MagicMock(return_value=iter([]))
        results.append(r)
    token_row = MagicMock()
    token_row.input = 0
    token_row.output = 0
    tokens = MagicMock()
    tokens.one.return_value = token_row
    results.append(tokens)
    r = MagicMock()
    r.__iter__ = MagicMock(return_value=iter([]))
    results.append(r)

    mock_session.execute = AsyncMock(side_effect=results)

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/monitoring/llm-stats",
            params={"period": "unknown_period"},
        )

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_list_traces_returns_summaries():
    """GET /monitoring/traces returns recent trace summaries."""
    app = _build_app()

    summaries = [
        {
            "trace_id": "trace-1",
            "channel": "telegram",
            "specialist": "diary",
            "status": "success",
            "span_count": 6,
            "total_latency_ms": 120,
            "error_count": 0,
            "created_at": "2026-04-09T22:00:00+00:00",
        }
    ]

    with patch(
        "src.app.api.routes.monitoring.summarize_traces",
        new=AsyncMock(return_value=summaries),
    ) as mock_repo:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/monitoring/traces")

    assert resp.status_code == 200
    assert resp.json()[0]["trace_id"] == "trace-1"
    mock_repo.assert_awaited_once()


@pytest.mark.asyncio
async def test_trace_detail_returns_trace():
    """GET /monitoring/traces/{trace_id} returns the trace span tree."""
    app = _build_app()

    detail = {
        "trace_id": "trace-1",
        "channel": "telegram",
        "specialist": "diary",
        "status": "success",
        "created_at": "2026-04-09T22:00:00+00:00",
        "spans": [
            {
                "id": "span-1",
                "parent_span_id": None,
                "name": "request.process_message",
                "span_kind": "request",
                "channel": "telegram",
                "specialist": "diary",
                "status": "success",
                "error_class": None,
                "model": None,
                "tokens_in": None,
                "tokens_out": None,
                "tool_name": None,
                "cache_hit": None,
                "latency_ms": 25,
                "details": {"source": "telegram"},
                "created_at": "2026-04-09T22:00:00+00:00",
            }
        ],
    }

    with patch(
        "src.app.api.routes.monitoring.get_trace_detail",
        new=AsyncMock(return_value=detail),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/monitoring/traces/trace-1")

    assert resp.status_code == 200
    assert resp.json()["spans"][0]["name"] == "request.process_message"


@pytest.mark.asyncio
async def test_eval_outcomes_returns_quality_metadata():
    """GET /monitoring/eval-outcomes returns structured quality and channel metadata."""
    mock_session = AsyncMock()
    record = _make_mock_action()
    record.response_id = "resp-1"
    record.specialist = "tools"
    record.source = "telegram"
    record.eval_status = "passed"
    record.quality_scores = {"route_quality": 1.0, "channel_style": 0.95}
    record.channel_metrics = {"chunk_count": 2, "render_passed": True}
    record.feedback_rating = "thumbs_up"

    result = MagicMock()
    result.scalars.return_value.all.return_value = [record]
    mock_session.execute = AsyncMock(return_value=result)

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/monitoring/eval-outcomes")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload[0]["response_id"] == "resp-1"
    assert payload[0]["quality_scores"]["route_quality"] == 1.0
    assert payload[0]["channel_metrics"]["chunk_count"] == 2


@pytest.mark.asyncio
async def test_channel_metrics_aggregates_by_source():
    """GET /monitoring/channel-metrics aggregates renderer metrics by source."""
    mock_session = AsyncMock()
    first = SimpleNamespace(
        source="telegram",
        duration_ms=100,
        channel_metrics={
            "chunk_count": 2,
            "render_passed": True,
            "delivery_status": "sent",
            "retry_count": 1,
            "reply_anchor_requested": True,
            "reply_anchor_dropped": False,
            "feedback_callback_attempts": 2,
            "feedback_callback_successes": 1,
        },
    )
    second = SimpleNamespace(
        source="telegram",
        duration_ms=200,
        channel_metrics={
            "chunk_count": 3,
            "render_passed": False,
            "delivery_status": "partial_failure",
            "retry_count": 3,
            "reply_anchor_requested": True,
            "reply_anchor_dropped": True,
            "feedback_callback_attempts": 1,
            "feedback_callback_successes": 0,
        },
    )
    third = SimpleNamespace(
        source="api",
        duration_ms=50,
        channel_metrics={
            "chunk_count": 1,
            "render_passed": True,
            "delivery_status": "sent",
            "retry_count": 0,
        },
    )

    result = MagicMock()
    result.scalars.return_value.all.return_value = [first, second, third]
    mock_session.execute = AsyncMock(return_value=result)

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/monitoring/channel-metrics")

    assert resp.status_code == 200
    payload = {item["source"]: item for item in resp.json()}
    assert payload["telegram"]["interaction_count"] == 2
    assert payload["telegram"]["avg_latency_ms"] == 150.0
    assert payload["telegram"]["avg_chunk_count"] == 2.5
    assert payload["telegram"]["render_failures"] == 1
    assert payload["telegram"]["delivery_failures"] == 1
    assert payload["telegram"]["delivery_success_rate"] == 0.5
    assert payload["telegram"]["avg_retry_count"] == 2.0
    assert payload["telegram"]["total_retry_count"] == 4
    assert payload["telegram"]["chunked_delivery_rate"] == 1.0
    assert payload["telegram"]["reply_anchor_drop_rate"] == 0.5
    assert payload["telegram"]["feedback_callback_success_rate"] == 0.333
    assert payload["api"]["delivery_failures"] == 0
    assert payload["api"]["feedback_callback_success_rate"] is None


@pytest.mark.asyncio
async def test_telegram_webhook_status_reports_degraded():
    """GET /monitoring/telegram-webhook surfaces degraded webhook state."""
    recent_error_date = int(datetime.now(UTC).timestamp()) - 30
    app = _build_app()
    app.state.telegram_service = SimpleNamespace(
        get_webhook_status=AsyncMock(
            return_value={
                "url": "https://example.com/telegram",
                "pending_update_count": 3,
                "last_error_date": recent_error_date,
                "last_error_message": "flood control",
                "max_connections": 40,
            }
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/monitoring/telegram-webhook")

    assert resp.status_code == 200
    assert resp.json()["status"] == "degraded"
    assert resp.json()["pending_update_count"] == 3
    assert resp.json()["webhook_lagging"] is True


@pytest.mark.asyncio
async def test_telegram_webhook_status_reports_lagging_without_errors():
    """GET /monitoring/telegram-webhook reports lagging when backlog exists without errors."""
    app = _build_app()
    app.state.telegram_service = SimpleNamespace(
        get_webhook_status=AsyncMock(
            return_value={
                "url": "https://example.com/telegram",
                "pending_update_count": 2,
                "last_error_date": None,
                "last_error_message": None,
                "max_connections": 40,
            }
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/monitoring/telegram-webhook")

    assert resp.status_code == 200
    assert resp.json()["status"] == "lagging"
    assert resp.json()["pending_update_count"] == 2
    assert resp.json()["webhook_lagging"] is True
    assert resp.json()["pending_updates_warning_threshold"] == 10


@pytest.mark.asyncio
async def test_ops_webhook_status_alias_reports_degraded():
    """GET /ops/webhook-status should mirror /monitoring/telegram-webhook output."""
    recent_error_date = int(datetime.now(UTC).timestamp()) - 45
    app = _build_app()
    app.state.telegram_service = SimpleNamespace(
        get_webhook_status=AsyncMock(
            return_value={
                "url": "https://example.com/telegram",
                "pending_update_count": 2,
                "last_error_date": recent_error_date,
                "last_error_message": "temporary failure",
                "max_connections": 20,
            }
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/ops/webhook-status")

    assert resp.status_code == 200
    assert resp.json()["status"] == "degraded"
    assert resp.json()["pending_update_count"] == 2


@pytest.mark.asyncio
async def test_telegram_webhook_status_ignores_stale_error_message():
    """Stale Telegram errors should not force degraded status when backlog is clear."""
    stale_error_date = int(datetime.now(UTC).timestamp()) - 7200
    app = _build_app()
    app.state.telegram_service = SimpleNamespace(
        get_webhook_status=AsyncMock(
            return_value={
                "url": "https://example.com/telegram",
                "pending_update_count": 0,
                "last_error_date": stale_error_date,
                "last_error_message": "temporary failure",
                "max_connections": 20,
            }
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/monitoring/telegram-webhook")

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["last_error_message"] == "temporary failure"


@pytest.mark.asyncio
async def test_release_readiness_reports_not_ready_when_sample_size_too_low():
    """GET /ops/release-readiness should fail when minimum interaction sample is not met."""
    mock_session = AsyncMock()

    interactions_result = MagicMock()
    interactions_result.scalars.return_value.all.return_value = [
        SimpleNamespace(
            trace_id="trace-1",
            quality_scores={
                "route_quality": 1.0,
                "channel_style": 1.0,
                "final_response_quality": 1.0,
            },
            channel_metrics={"render_passed": True},
        )
    ]
    tool_receipts_result = MagicMock()
    tool_receipts_result.scalars.return_value.all.return_value = [
        SimpleNamespace(
            status="executed",
            mutation_class="mutating",
            audit_metadata={"confirmation_required": True},
        )
    ]
    mock_session.execute = AsyncMock(side_effect=[interactions_result, tool_receipts_result])

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db
    app.state.preflight_report = {"status": "ok"}

    readiness_settings = SimpleNamespace(
        quality_gate_route_accuracy_target=0.95,
        quality_gate_channel_style_pass_rate_target=0.95,
        quality_gate_channel_style_score_threshold=0.95,
        quality_gate_final_response_quality_pass_rate_target=0.90,
        quality_gate_final_response_quality_score_threshold=0.90,
        quality_gate_renderer_pass_rate_target=0.95,
        quality_gate_trace_coverage_target=1.0,
        quality_gate_tool_execution_success_rate_target=0.90,
        quality_gate_confirmation_coverage_target=1.0,
        quality_gates_alert_min_interactions=2,
        workflow_live_runtime_enabled=True,
        auto_judge_enabled=True,
        quality_gates_alerts_enabled=True,
        session_maintenance_enabled=True,
        sentry_configured=True,
        posthog_configured=True,
    )

    with patch(
        "src.app.api.routes.monitoring.get_settings",
        return_value=readiness_settings,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/ops/release-readiness")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ready"] is False
    assert "quality_gate_sample_size" in payload["failing_checks"]
    assert payload["quality_gates"]["sample_sizes"]["interactions"] == 1


@pytest.mark.asyncio
async def test_release_readiness_reports_ready_when_all_checks_pass():
    """GET /ops/release-readiness should pass when checks and quality gates are clear."""
    mock_session = AsyncMock()

    interactions_result = MagicMock()
    interactions_result.scalars.return_value.all.return_value = [
        SimpleNamespace(
            trace_id="trace-1",
            quality_scores={
                "route_quality": 1.0,
                "channel_style": 0.99,
                "final_response_quality": 0.95,
            },
            channel_metrics={"render_passed": True},
        ),
        SimpleNamespace(
            trace_id="trace-2",
            quality_scores={
                "route_quality": 1.0,
                "channel_style": 0.96,
                "final_response_quality": 0.92,
            },
            channel_metrics={"render_passed": True},
        ),
    ]
    tool_receipts_result = MagicMock()
    tool_receipts_result.scalars.return_value.all.return_value = [
        SimpleNamespace(
            status="executed",
            mutation_class="mutating",
            audit_metadata={"confirmation_required": True},
        ),
        SimpleNamespace(
            status="executed",
            mutation_class="read_only",
            audit_metadata={},
        ),
    ]
    mock_session.execute = AsyncMock(side_effect=[interactions_result, tool_receipts_result])

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db
    app.state.startup_preflight_report = {"status": "ok"}

    readiness_settings = SimpleNamespace(
        quality_gate_route_accuracy_target=0.95,
        quality_gate_channel_style_pass_rate_target=0.95,
        quality_gate_channel_style_score_threshold=0.95,
        quality_gate_final_response_quality_pass_rate_target=0.90,
        quality_gate_final_response_quality_score_threshold=0.90,
        quality_gate_renderer_pass_rate_target=0.95,
        quality_gate_trace_coverage_target=1.0,
        quality_gate_tool_execution_success_rate_target=0.90,
        quality_gate_confirmation_coverage_target=1.0,
        quality_gates_alert_min_interactions=2,
        workflow_live_runtime_enabled=True,
        auto_judge_enabled=True,
        quality_gates_alerts_enabled=True,
        session_maintenance_enabled=True,
        sentry_configured=True,
        posthog_configured=True,
    )

    with patch(
        "src.app.api.routes.monitoring.get_settings",
        return_value=readiness_settings,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/ops/release-readiness")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ready"] is True
    assert payload["failing_checks"] == []
    assert payload["gate_failures"] == []
    assert payload["quality_gates"]["route_accuracy"] == 1.0


@pytest.mark.asyncio
async def test_release_readiness_reports_not_ready_when_assistant_native_replays_fail():
    """GET /ops/release-readiness should fail when replay coverage regresses."""
    mock_session = AsyncMock()

    interactions_result = MagicMock()
    interactions_result.scalars.return_value.all.return_value = [
        SimpleNamespace(
            trace_id="trace-1",
            quality_scores={
                "route_quality": 1.0,
                "channel_style": 1.0,
                "final_response_quality": 1.0,
            },
            channel_metrics={"render_passed": True},
        ),
        SimpleNamespace(
            trace_id="trace-2",
            quality_scores={
                "route_quality": 1.0,
                "channel_style": 1.0,
                "final_response_quality": 1.0,
            },
            channel_metrics={"render_passed": True},
        ),
    ]
    tool_receipts_result = MagicMock()
    tool_receipts_result.scalars.return_value.all.return_value = [
        SimpleNamespace(
            status="executed",
            mutation_class="mutating",
            audit_metadata={"confirmation_required": True},
        )
    ]
    mock_session.execute = AsyncMock(side_effect=[interactions_result, tool_receipts_result])

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db
    app.state.startup_preflight_report = {"status": "ok"}

    readiness_settings = SimpleNamespace(
        quality_gate_route_accuracy_target=0.95,
        quality_gate_channel_style_pass_rate_target=0.95,
        quality_gate_channel_style_score_threshold=0.95,
        quality_gate_final_response_quality_pass_rate_target=0.90,
        quality_gate_final_response_quality_score_threshold=0.90,
        quality_gate_renderer_pass_rate_target=0.95,
        quality_gate_trace_coverage_target=1.0,
        quality_gate_tool_execution_success_rate_target=0.90,
        quality_gate_confirmation_coverage_target=1.0,
        quality_gates_alert_min_interactions=2,
        workflow_live_runtime_enabled=True,
        auto_judge_enabled=True,
        quality_gates_alerts_enabled=True,
        session_maintenance_enabled=True,
        continuity_runtime_enabled=True,
        project_draft_runtime_enabled=True,
        notes_workspace_enabled=True,
        content_factory_enabled=True,
        assistant_native_replay_eval_enabled=True,
        assistant_native_replay_pass_rate_target=1.0,
        assistant_native_replay_baseline_lift_target=0.5,
        sentry_configured=True,
        posthog_configured=True,
    )

    with (
        patch(
            "src.app.api.routes.monitoring.get_settings",
            return_value=readiness_settings,
        ),
        patch(
            "src.app.api.routes.monitoring.validate_assistant_native_eval_assets",
            return_value=[],
        ),
        patch(
            "src.app.api.routes.monitoring.evaluate_assistant_native_replays",
            return_value=SimpleNamespace(
                pass_rate=0.5,
                baseline_lift=0.1,
                failing_case_ids=["retry_pending_save_note"],
            ),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/ops/release-readiness")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ready"] is False
    assert "assistant_native_replay_pass_rate" in payload["failing_checks"]
    assert "assistant_native_replay_baseline_lift" in payload["failing_checks"]


@pytest.mark.asyncio
async def test_context_snapshot_recovers_pending_tool_plan_from_checkpoint():
    """GET /monitoring/ops/context should surface durable pending approvals when Redis misses."""
    mock_conv_ctx = MagicMock()
    mock_conv_ctx.get_context = AsyncMock(return_value=[])
    mock_conv_ctx.get_summary = AsyncMock(return_value="")
    mock_conv_ctx.get_state_packet = AsyncMock(return_value=None)
    mock_conv_ctx.get_pending_tool_plan = AsyncMock(return_value=None)

    checkpoint = SimpleNamespace(
        id="checkpoint-1",
        workflow_id="11111111-1111-1111-1111-111111111111",
        payload={
            "plan_id": "plan-1",
            "original_user_message": "Schedule lunch tomorrow",
            "trust_label": "trusted_user",
            "tool_calls": [
                {
                    "tool_use_id": "tool-1",
                    "name": "google-calendar__create_event",
                    "input": {"title": "Lunch"},
                    "idempotency_key": "idem-1",
                    "audit": {"confirmation_required": True},
                }
            ],
        },
    )

    app = _build_app()

    with (
        patch(
            "src.app.api.routes.monitoring._get_conversation_context", return_value=mock_conv_ctx
        ),
        patch(
            "src.app.api.routes.monitoring.get_latest_pending_workflow_checkpoint_for_user",
            new_callable=AsyncMock,
            return_value=checkpoint,
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/ops/context/user-1")

    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is True
    assert data["pending_tool_plan"]["plan_id"] == "plan-1"
    assert data["pending_tool_plan"]["workflow_id"] == "11111111-1111-1111-1111-111111111111"
    assert data["pending_tool_plan"]["checkpoint_id"] == "checkpoint-1"

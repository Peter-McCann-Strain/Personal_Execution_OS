"""Integration tests for monitoring endpoints through the full FastAPI app."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch


def _make_action(
    *,
    agent_name: str = "diary",
    cost_usd: float = 0.001,
    duration_ms: int = 500,
) -> MagicMock:
    now = datetime(2026, 3, 15, 10, 0, tzinfo=UTC)
    action = MagicMock()
    action.id = uuid.uuid4()
    action.agent_name = agent_name
    action.action_type = "process"
    action.model_used = "claude-haiku"
    action.tokens_in = 100
    action.tokens_out = 200
    action.cost_usd = cost_usd
    action.duration_ms = duration_ms
    action.input_summary = "Input"
    action.output_summary = "Output"
    action.trace_id = "trace-123"
    action.created_at = now
    return action


class TestMonitoringContracts:
    """Verify monitoring response contracts through the real app router."""

    async def test_list_agent_actions_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client

        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = [_make_action()]
        mock_session.execute = AsyncMock(side_effect=[count_result, data_result])

        response = await client.get("/api/monitoring/actions")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["agent_name"] == "diary"
        assert data["items"][0]["cost_usd"] == 0.001

    async def test_llm_stats_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client

        cost_today = MagicMock()
        cost_today.scalar_one.return_value = 0.05
        cost_week = MagicMock()
        cost_week.scalar_one.return_value = 0.35
        cost_month = MagicMock()
        cost_month.scalar_one.return_value = 1.2

        trend_row = MagicMock()
        trend_row.d = "2026-03-15"
        trend_row.cost = 0.05
        cost_trend = MagicMock()
        cost_trend.__iter__ = MagicMock(return_value=iter([trend_row]))

        model_row = MagicMock()
        model_row.model = "claude-haiku"
        model_row.cost = 0.3
        cost_by_model = MagicMock()
        cost_by_model.__iter__ = MagicMock(return_value=iter([model_row]))

        agent_row = MagicMock()
        agent_row.agent = "diary"
        agent_row.cost = 0.2
        cost_by_agent = MagicMock()
        cost_by_agent.__iter__ = MagicMock(return_value=iter([agent_row]))

        token_row = MagicMock()
        token_row.input = 5000
        token_row.output = 8000
        tokens = MagicMock()
        tokens.one.return_value = token_row

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
            ],
        )

        response = await client.get("/api/monitoring/llm-stats", params={"period": "7d"})

        assert response.status_code == 200
        data = response.json()
        assert data["cost"]["today"] == 0.05
        assert data["cost"]["week"] == 0.35
        assert data["cost"]["month"] == 1.2
        assert data["tokens"]["input"] == 5000
        assert data["tokens"]["output"] == 8000
        assert data["latency_by_agent"][0]["agent"] == "diary"

    async def test_llm_stats_defaults_unknown_period_to_week_contract(
        self,
        integration_client,
    ):
        client, mock_session, _mock_anthropic = integration_client

        cost_today = MagicMock()
        cost_today.scalar_one.return_value = 0.0
        cost_week = MagicMock()
        cost_week.scalar_one.return_value = 0.0
        cost_month = MagicMock()
        cost_month.scalar_one.return_value = 0.0

        trend_row = MagicMock()
        trend_row.d = "2026-04-08"
        trend_row.cost = 0.0
        cost_trend = MagicMock()
        cost_trend.__iter__ = MagicMock(return_value=iter([trend_row]))

        cost_by_model = MagicMock()
        cost_by_model.__iter__ = MagicMock(return_value=iter([]))
        cost_by_agent = MagicMock()
        cost_by_agent.__iter__ = MagicMock(return_value=iter([]))

        token_row = MagicMock()
        token_row.input = 0
        token_row.output = 0
        tokens = MagicMock()
        tokens.one.return_value = token_row

        latency = MagicMock()
        latency.__iter__ = MagicMock(return_value=iter([]))

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
            ],
        )

        response = await client.get("/api/monitoring/llm-stats", params={"period": "bogus"})

        assert response.status_code == 200
        data = response.json()
        assert data["cost"]["today"] == 0.0
        assert data["cost"]["week"] == 0.0
        assert data["cost"]["month"] == 0.0
        assert data["cost_trend"] == [{"date": "2026-04-08", "cost": 0.0}]

    async def test_agent_comparison_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client

        summary_row = MagicMock()
        summary_row.agent = "diary"
        summary_row.call_count = 42
        summary_row.avg_cost = 0.001
        summary_row.avg_latency_ms = 450.0
        summary_row.error_rate = 0.02
        summary_row.total_tokens = 15000
        summaries = MagicMock()
        summaries.__iter__ = MagicMock(return_value=iter([summary_row]))

        usage_row = MagicMock()
        usage_row.agent = "diary"
        usage_row.calls = 42
        usage = MagicMock()
        usage.__iter__ = MagicMock(return_value=iter([usage_row]))

        mock_session.execute = AsyncMock(side_effect=[summaries, usage])

        response = await client.get("/api/monitoring/agent-comparison", params={"period": "30d"})

        assert response.status_code == 200
        data = response.json()
        assert len(data["summaries"]) == 1
        assert data["summaries"][0]["agent"] == "diary"
        assert data["summaries"][0]["call_count"] == 42
        assert data["usage_distribution"][0]["calls"] == 42

    async def test_prompt_versions_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client

        response = await client.get("/api/monitoring/prompt-versions")

        assert response.status_code == 200
        data = response.json()
        assert any(item["agent"] == "routing" for item in data)

        tools_record = next(item for item in data if item["agent"] == "tools")
        assert tools_record["kind"] == "specialist"
        assert isinstance(tools_record["prompt_source"], str)
        assert isinstance(tools_record["allowed_tool_patterns"], list)

    async def test_get_interaction_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client
        interaction_id = uuid.uuid4()
        record = _make_action()
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

        with patch(
            "src.app.api.routes.monitoring.repo_get_interaction_by_id",
            new_callable=AsyncMock,
            return_value=record,
        ):
            response = await client.get(f"/api/monitoring/interactions/{interaction_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == "user-1"
        assert data["response_agent"] == "tools"
        assert data["score_conciseness"] == 0.5

    async def test_get_interaction_not_found_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client
        interaction_id = uuid.uuid4()

        with patch(
            "src.app.api.routes.monitoring.repo_get_interaction_by_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await client.get(f"/api/monitoring/interactions/{interaction_id}")

        assert response.status_code == 404
        assert response.json()["error"] == "not_found"

    async def test_quality_scores_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client

        with patch(
            "src.app.api.routes.monitoring.repo_get_avg_scores",
            new=AsyncMock(
                return_value={
                    "relevance": 0.91234,
                    "actionability": None,
                    "tone": 0.123456,
                    "conciseness": None,
                    "count": 7,
                },
            ),
        ):
            response = await client.get(
                "/api/monitoring/quality-scores",
                params={
                    "start": "2026-04-01T00:00:00",
                    "end": "2026-04-07T00:00:00",
                    "specialist": "tools",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["relevance"] == 0.9123
        assert data["actionability"] is None
        assert data["tone"] == 0.1235
        assert data["count"] == 7

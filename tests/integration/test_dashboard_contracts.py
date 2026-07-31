"""Integration tests for dashboard endpoints consumed by the frontend."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch


def _make_episode(*, content: str = "Morning walk") -> MagicMock:
    episode = MagicMock()
    episode.id = uuid.uuid4()
    episode.content = content
    episode.summary = "Summary"
    episode.episode_type = "diary"
    episode.para_category = None
    episode.mood_score = 7.0
    episode.energy_rating = 6.5
    episode.tags = []
    episode.people_mentioned = []
    episode.source = "api"
    episode.created_at = datetime(2026, 4, 8, 9, 0, 0, tzinfo=UTC)
    return episode


def _make_goal() -> MagicMock:
    goal = MagicMock()
    goal.id = uuid.uuid4()
    goal.title = "Ship API contracts"
    goal.goal_type = "project"
    goal.parent_id = None
    goal.priority = 1
    goal.status = "active"
    goal.progress = 0.75
    goal.deadline = None
    goal.evidence = []
    goal.created_at = datetime(2026, 4, 1, 8, 0, 0, tzinfo=UTC)
    goal.updated_at = datetime(2026, 4, 8, 8, 0, 0, tzinfo=UTC)
    return goal


def _make_action() -> MagicMock:
    action = MagicMock()
    action.id = uuid.uuid4()
    action.agent_name = "diary"
    action.action_type = "process"
    action.model_used = "claude-haiku"
    action.tokens_in = 100
    action.tokens_out = 200
    action.cost_usd = 0.001
    action.duration_ms = 450
    action.input_summary = "Input"
    action.output_summary = "Output"
    action.trace_id = "trace-123"
    action.created_at = datetime(2026, 4, 8, 10, 0, 0, tzinfo=UTC)
    return action


class TestDashboardContracts:
    """Exercise the real dashboard routes via the full FastAPI app."""

    async def test_dashboard_stats_returns_frontend_shape(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client

        mood_result = MagicMock()
        mood_result.scalar.return_value = 7.3

        project_result = MagicMock()
        project_result.scalar.return_value = 3

        mock_session.execute = AsyncMock(side_effect=[mood_result, project_result])

        with patch(
            "src.app.api.routes.dashboard.get_settings",
            return_value=MagicMock(google_configured=False),
        ):
            response = await client.get("/api/dashboard/stats")

        assert response.status_code == 200
        data = response.json()
        assert data["mood"]["value"] == 7.3
        assert data["mood"]["subLabel"] == "Last 7 days"
        assert data["projects"]["value"] == 3.0
        assert data["emails"]["status"] == "not_configured"
        assert data["events"]["status"] == "not_configured"

    async def test_dashboard_stats_returns_live_google_metrics_when_configured(
        self,
        integration_client,
    ):
        client, mock_session, _mock_anthropic = integration_client

        mood_result = MagicMock()
        mood_result.scalar.return_value = 6.8

        project_result = MagicMock()
        project_result.scalar.return_value = 2

        mock_session.execute = AsyncMock(side_effect=[mood_result, project_result])

        with (
            patch(
                "src.app.api.routes.dashboard.get_settings",
                return_value=MagicMock(google_configured=True),
            ),
            patch(
                "src.app.api.routes.dashboard._get_unread_email_count",
                new_callable=AsyncMock,
                return_value=5,
            ),
            patch(
                "src.app.api.routes.dashboard._get_todays_calendar_events",
                new_callable=AsyncMock,
                return_value=[
                    {
                        "id": "evt-1",
                        "summary": "Standup",
                        "start": "2026-04-08T09:00:00+00:00",
                        "end": "2026-04-08T09:30:00+00:00",
                        "location": None,
                        "description": None,
                        "attendees": [],
                    },
                    {
                        "id": "evt-2",
                        "summary": "Review",
                        "start": "2026-04-08T11:00:00+00:00",
                        "end": "2026-04-08T11:30:00+00:00",
                        "location": None,
                        "description": None,
                        "attendees": [],
                    },
                ],
            ),
        ):
            response = await client.get("/api/dashboard/stats")

        assert response.status_code == 200
        data = response.json()
        assert data["emails"]["status"] == "available"
        assert data["emails"]["value"] == 5.0
        assert data["events"]["status"] == "available"
        assert data["events"]["value"] == 2.0

    async def test_morning_briefing_returns_notices_for_unconfigured_services(
        self,
        integration_client,
    ):
        client, _mock_session, _mock_anthropic = integration_client

        with (
            patch(
                "src.app.api.routes.dashboard.get_settings",
                return_value=MagicMock(google_configured=False, tavily_configured=False),
            ),
            patch(
                "src.app.api.routes.dashboard._get_priority_notifications",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            response = await client.get("/api/dashboard/briefing")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "not_configured"
        assert data["greeting"]["summary"] == "Your briefing is ready."
        assert {notice["source"] for notice in data["notices"]} == {
            "calendar",
            "content",
        }

    async def test_morning_briefing_returns_live_sections_when_available(
        self,
        integration_client,
    ):
        client, _mock_session, _mock_anthropic = integration_client

        with (
            patch(
                "src.app.api.routes.dashboard.get_settings",
                return_value=MagicMock(google_configured=True, tavily_configured=True),
            ),
            patch(
                "src.app.api.routes.dashboard._get_todays_calendar_events",
                new_callable=AsyncMock,
                return_value=[
                    {
                        "id": "evt-1",
                        "summary": "Planning block",
                        "start": "2026-04-08T09:00:00+00:00",
                        "end": "2026-04-08T10:00:00+00:00",
                        "location": None,
                        "description": None,
                        "attendees": [],
                    }
                ],
            ),
            patch(
                "src.app.api.routes.dashboard._get_priority_notifications",
                new_callable=AsyncMock,
                return_value=[
                    {
                        "id": "notif-1",
                        "message": "Deadline approaching",
                        "priority": "P1",
                        "category": "deadline",
                        "created_at": "2026-04-08T08:30:00+00:00",
                        "dismissed": False,
                    }
                ],
            ),
            patch(
                "src.app.api.routes.dashboard._get_curated_content",
                new_callable=AsyncMock,
                return_value=[
                    {
                        "title": "AI infrastructure update",
                        "source": "Tavily",
                        "url": "https://example.com/article",
                        "relevance": 0.91,
                    }
                ],
            ),
        ):
            response = await client.get("/api/dashboard/briefing")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert len(data["schedule"]) == 1
        assert len(data["notifications"]) == 1
        assert len(data["content"]) == 1
        assert data["notices"] == []
        assert (
            data["greeting"]["summary"]
            == "Today includes 1 event, 1 priority notification, 1 curated item."
        )

    async def test_mood_energy_trends_returns_time_series_points(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client

        row = MagicMock()
        row.date = "2026-04-08"
        row.mood = 7.5
        row.energy = 6.8

        result = MagicMock()
        result.all.return_value = [row]
        mock_session.execute = AsyncMock(return_value=result)

        response = await client.get("/api/dashboard/trends/mood-energy", params={"days": 7})

        assert response.status_code == 200
        assert response.json() == [{"date": "2026-04-08", "mood": 7.5, "energy": 6.8}]

    async def test_recent_diary_entries_returns_episode_dtos(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client

        result = MagicMock()
        result.scalars.return_value.all.return_value = [_make_episode()]
        mock_session.execute = AsyncMock(return_value=result)

        response = await client.get("/api/dashboard/diary/recent", params={"limit": 1})

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["content"] == "Morning walk"
        assert data[0]["episode_type"] == "diary"

    async def test_active_goals_returns_goal_dtos(self, integration_client):
        client, _unused_session, _mock_anthropic = integration_client

        with patch(
            "src.app.api.routes.dashboard.list_goals",
            new_callable=AsyncMock,
            return_value=[_make_goal()],
        ):
            response = await client.get("/api/dashboard/goals", params={"limit": 1})

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "Ship API contracts"
        assert data[0]["status"] == "active"

    async def test_recent_agent_activity_returns_activity_feed(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client

        result = MagicMock()
        result.scalars.return_value.all.return_value = [_make_action()]
        mock_session.execute = AsyncMock(return_value=result)

        response = await client.get("/api/dashboard/activity/recent", params={"limit": 1})

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["agent_name"] == "diary"
        assert data[0]["trace_id"] == "trace-123"

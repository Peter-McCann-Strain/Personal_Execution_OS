"""Integration tests for habits endpoints through the full FastAPI app."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch


def _make_habit(
    *,
    habit_id: uuid.UUID | None = None,
    name: str = "Meditate",
    description: str | None = "10 minutes daily",
    frequency: str = "daily",
    frequency_days: int = 1,
    current_streak: int = 5,
    longest_streak: int = 12,
    total_completions: int = 30,
    active: bool = True,
    tags: list[str] | None = None,
) -> MagicMock:
    now = datetime(2026, 3, 15, 10, 0, tzinfo=UTC)
    habit = MagicMock()
    habit.id = habit_id or uuid.uuid4()
    habit.name = name
    habit.description = description
    habit.frequency = frequency
    habit.frequency_days = frequency_days
    habit.current_streak = current_streak
    habit.longest_streak = longest_streak
    habit.total_completions = total_completions
    habit.last_completed_at = now
    habit.active = active
    habit.tags = tags or ["wellness"]
    habit.created_at = now
    return habit


def _make_log(
    *,
    log_id: uuid.UUID | None = None,
    habit_id: uuid.UUID | None = None,
    note: str | None = "Felt great today",
    source: str = "manual",
) -> MagicMock:
    now = datetime(2026, 3, 15, 10, 0, tzinfo=UTC)
    log = MagicMock()
    log.id = log_id or uuid.uuid4()
    log.habit_id = habit_id or uuid.uuid4()
    log.completed_at = now
    log.note = note
    log.source = source
    return log


class TestHabitContracts:
    """Verify habit response contracts through the real app router."""

    async def test_list_habits_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client

        with patch(
            "src.app.api.routes.habits.repo_get_active_habits",
            new_callable=AsyncMock,
            return_value=[_make_habit()],
        ):
            response = await client.get("/api/habits")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Meditate"
        assert data[0]["current_streak"] == 5
        assert data[0]["longest_streak"] == 12

    async def test_create_habit_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client
        habit_id = uuid.uuid4()

        with patch(
            "src.app.api.routes.habits.repo_create_habit",
            new_callable=AsyncMock,
            return_value=_make_habit(habit_id=habit_id, name="Exercise"),
        ):
            response = await client.post(
                "/api/habits",
                json={"name": "Exercise", "frequency": "daily", "frequency_days": 1},
            )

        assert response.status_code == 201
        data = response.json()
        assert data["id"] == str(habit_id)
        assert data["name"] == "Exercise"
        mock_session.refresh.assert_awaited()

    async def test_get_habit_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client
        habit_id = uuid.uuid4()

        with patch(
            "src.app.api.routes.habits.repo_get_habit_by_id",
            new_callable=AsyncMock,
            return_value=_make_habit(habit_id=habit_id),
        ):
            response = await client.get(f"/api/habits/{habit_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(habit_id)
        assert data["name"] == "Meditate"
        assert data["current_streak"] == 5

    async def test_complete_habit_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client
        habit_id = uuid.uuid4()

        with (
            patch(
                "src.app.api.routes.habits.repo_get_habit_by_id",
                new_callable=AsyncMock,
                return_value=_make_habit(habit_id=habit_id),
            ),
            patch(
                "src.app.api.routes.habits.repo_log_habit_completion",
                new_callable=AsyncMock,
                return_value=_make_log(habit_id=habit_id),
            ),
        ):
            response = await client.post(
                f"/api/habits/{habit_id}/complete",
                json={"note": "Felt great today"},
            )

        assert response.status_code == 201
        data = response.json()
        assert data["habit_id"] == str(habit_id)
        assert data["source"] == "manual"
        assert data["note"] == "Felt great today"
        mock_session.refresh.assert_awaited()

    async def test_list_habit_logs_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client
        habit_id = uuid.uuid4()

        with (
            patch(
                "src.app.api.routes.habits.repo_get_habit_by_id",
                new_callable=AsyncMock,
                return_value=_make_habit(habit_id=habit_id),
            ),
            patch(
                "src.app.api.routes.habits.repo_get_habit_logs",
                new_callable=AsyncMock,
                return_value=[_make_log(habit_id=habit_id)],
            ),
        ):
            response = await client.get(f"/api/habits/{habit_id}/logs")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["habit_id"] == str(habit_id)
        assert data[0]["note"] == "Felt great today"

    async def test_get_habit_not_found_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client
        habit_id = uuid.uuid4()

        with patch(
            "src.app.api.routes.habits.repo_get_habit_by_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await client.get(f"/api/habits/{habit_id}")

        assert response.status_code == 404
        assert response.json()["error"] == "not_found"

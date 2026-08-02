"""Tests for shared handler utilities (_common.py)."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.core.exceptions import DatabaseError
from src.app.domain.services.handlers import _common as common_module


@pytest.mark.asyncio
async def test_enqueue_entity_extraction_success():
    """enqueue_entity_extraction creates a Redis pool, enqueues a job, and closes."""
    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock()
    mock_pool.aclose = AsyncMock()

    with patch.object(common_module, "get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            redis_url=MagicMock(get_secret_value=lambda: "redis://localhost:6379")
        )

        with patch(
            "arq.connections.create_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            await common_module.enqueue_entity_extraction("ep-123", "Some text content")

    mock_pool.enqueue_job.assert_awaited_once_with(
        "process_agent_task",
        "entity_extraction",
        {"episode_id": "ep-123", "text": "Some text content"},
    )
    mock_pool.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_enqueue_entity_extraction_raises_on_redis_failure():
    """enqueue_entity_extraction should fail loudly when Redis is unavailable."""
    with patch.object(common_module, "get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            redis_url=MagicMock(get_secret_value=lambda: "redis://localhost:6379")
        )

        with (
            patch(
                "arq.connections.create_pool",
                new_callable=AsyncMock,
                side_effect=ConnectionError("Redis unreachable"),
            ),
            pytest.raises(
                DatabaseError,
                match="Entity extraction enqueue failed with ConnectionError: Redis unreachable",
            ),
        ):
            await common_module.enqueue_entity_extraction("ep-456", "Some text")


@pytest.mark.asyncio
async def test_enqueue_entity_extraction_raises_on_import_error():
    """enqueue_entity_extraction should fail loudly on unexpected queue errors."""
    with patch.object(common_module, "get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            redis_url=MagicMock(get_secret_value=lambda: "redis://localhost:6379")
        )

        with (
            patch(
                "arq.connections.create_pool",
                new_callable=AsyncMock,
                side_effect=Exception("Unexpected error"),
            ),
            pytest.raises(
                DatabaseError,
                match="Entity extraction enqueue failed with Exception: Unexpected error",
            ),
        ):
            await common_module.enqueue_entity_extraction("ep-789", "More text")


@pytest.mark.asyncio
async def test_enqueue_agent_task_passes_typed_defer_interval():
    mock_pool = AsyncMock()

    with (
        patch.object(common_module, "get_settings") as mock_settings,
        patch(
            "arq.connections.create_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ),
    ):
        mock_settings.return_value = MagicMock(
            redis_url=MagicMock(get_secret_value=lambda: "redis://localhost:6379")
        )
        await common_module.enqueue_agent_task(
            "delayed_task",
            {"item_id": "item-1"},
            error_label="Delayed task",
            defer_by_seconds=2.5,
        )

    mock_pool.enqueue_job.assert_awaited_once_with(
        "process_agent_task",
        "delayed_task",
        {"item_id": "item-1"},
        _defer_by=timedelta(seconds=2.5),
    )
    mock_pool.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_enqueue_commitment_extraction_success():
    """enqueue_commitment_extraction creates a Redis pool, enqueues, and closes."""
    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock()
    mock_pool.aclose = AsyncMock()

    with patch.object(common_module, "get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            redis_url=MagicMock(get_secret_value=lambda: "redis://localhost:6379")
        )

        with patch(
            "arq.connections.create_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            await common_module.enqueue_commitment_extraction("ep-999", "Commitment text")

    mock_pool.enqueue_job.assert_awaited_once_with(
        "process_agent_task",
        "commitment_extraction",
        {"episode_id": "ep-999", "text": "Commitment text"},
    )
    mock_pool.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_enqueue_commitment_extraction_raises_on_failure():
    """enqueue_commitment_extraction should fail loudly when Redis is unavailable."""
    with patch.object(common_module, "get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            redis_url=MagicMock(get_secret_value=lambda: "redis://localhost:6379")
        )

        with (
            patch(
                "arq.connections.create_pool",
                new_callable=AsyncMock,
                side_effect=ConnectionError("Redis unreachable"),
            ),
            pytest.raises(
                DatabaseError,
                match="Commitment extraction enqueue failed with ConnectionError: Redis unreachable",
            ),
        ):
            await common_module.enqueue_commitment_extraction("ep-1000", "Commitment text")

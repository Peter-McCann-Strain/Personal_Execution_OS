"""Tests for the ARQ dead-letter queue (Phase 7.1).

Covers:
* ``write_dlq_row`` only runs on terminal job failure (exhausted retries).
* ``capture_poison_pill`` records deserialization failures with a base64 payload.
* DLQ insert failures are swallowed (best-effort contract).
* CLI list / show / replay happy paths using mocked ARQ + session factory.
* ``run_dlq_alerts`` skips when clean and fires Telegram when rows age out.
"""

from __future__ import annotations

import base64
import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from arq import Retry

from src.app.workers.agent_tasks import (
    capture_poison_pill,
    process_agent_task,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_factory() -> MagicMock:
    """Mock session factory where sessions track ``.add``-ed instances."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    added: list[object] = []

    def _add(instance: object) -> None:
        added.append(instance)

    session.add = MagicMock(side_effect=_add)

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock(return_value=cm)
    factory._session = session
    factory._added = added
    return factory


def _make_ctx(*, job_try: int, session_factory: MagicMock | None = None) -> dict:
    ctx: dict = {
        "job_try": job_try,
        "job_id": "job-abc-123",
        "llm_provider": SimpleNamespace(configured=True),
    }
    if session_factory is not None:
        ctx["session_factory"] = session_factory
    return ctx


# ---------------------------------------------------------------------------
# Terminal-failure path
# ---------------------------------------------------------------------------


class TestProcessAgentTaskDLQWrite:
    @pytest.mark.asyncio
    async def test_successful_job_does_not_write_dlq(self):
        """Happy-path jobs must NOT create DLQ rows."""
        factory = _make_session_factory()
        ctx = _make_ctx(job_try=1, session_factory=factory)

        # The entity_extraction handler is a suitable happy path — replace it
        # with a stub via the handlers map by patching the function it calls.
        with patch(
            "src.app.workers.agent_tasks._run_entity_extraction",
            new_callable=AsyncMock,
            return_value={"status": "ok"},
        ):
            result = await process_agent_task(
                ctx,
                "entity_extraction",
                {"episode_id": "ep-1", "text": "hello"},
            )

        assert result == {"status": "ok"}
        assert factory._added == []

    @pytest.mark.asyncio
    async def test_intermediate_retry_does_not_write_dlq(self):
        """On retry-able attempts we must raise ``Retry``, not write DLQ."""
        factory = _make_session_factory()
        ctx = _make_ctx(job_try=1, session_factory=factory)

        boom = RuntimeError("transient")
        with (
            patch(
                "src.app.workers.agent_tasks._run_entity_extraction",
                new_callable=AsyncMock,
                side_effect=boom,
            ),
            pytest.raises(Retry),
        ):
            await process_agent_task(
                ctx,
                "entity_extraction",
                {"episode_id": "ep-1", "text": "x"},
            )
        assert factory._added == []

    @pytest.mark.asyncio
    async def test_exhausted_retries_writes_dlq_row(self):
        """On the final attempt, the terminal exception + traceback land in DLQ."""
        factory = _make_session_factory()
        ctx = _make_ctx(job_try=3, session_factory=factory)

        boom = ValueError("permanent failure — bad payload")
        with patch(
            "src.app.workers.agent_tasks._run_entity_extraction",
            new_callable=AsyncMock,
            side_effect=boom,
        ):
            result = await process_agent_task(
                ctx,
                "entity_extraction",
                {"episode_id": "ep-1", "text": "oops"},
            )

        assert result["status"] == "error"
        assert "3 attempts" in result["message"]

        # Exactly one DLQ row written.
        assert len(factory._added) == 1
        row = factory._added[0]
        assert row.function == "process_agent_task:entity_extraction"
        assert row.exception_class == "ValueError"
        assert "permanent failure" in (row.exception_message or "")
        # Payload preserved for replay.
        assert row.kwargs == {
            "payload": {"episode_id": "ep-1", "text": "oops"},
        }
        assert row.args == ["entity_extraction"]
        assert row.retry_count == 3
        assert row.job_id == "job-abc-123"
        # Traceback was captured.
        assert row.traceback is not None

    @pytest.mark.asyncio
    async def test_dlq_write_failure_is_swallowed(self):
        """If the DLQ insert itself blows up, the worker must NOT re-raise."""
        factory = _make_session_factory()
        factory._session.commit.side_effect = RuntimeError("db is down")
        ctx = _make_ctx(job_try=3, session_factory=factory)

        boom = ValueError("x")
        with patch(
            "src.app.workers.agent_tasks._run_entity_extraction",
            new_callable=AsyncMock,
            side_effect=boom,
        ):
            # Must not raise — DLQ write is best-effort.
            result = await process_agent_task(
                ctx,
                "entity_extraction",
                {"episode_id": "ep", "text": "x"},
            )
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Poison-pill path
# ---------------------------------------------------------------------------


class TestCapturePoisonPill:
    @pytest.mark.asyncio
    async def test_writes_dlq_with_base64_payload(self):
        """Unknown-function payload lands in DLQ with function=<unknown>."""
        factory = _make_session_factory()
        ctx = {"session_factory": factory}

        raw = b"\x00\x01\x02not valid arq blob"
        expected_b64 = base64.b64encode(raw).decode("ascii")
        exc = RuntimeError("cannot deserialize job payload")

        await capture_poison_pill(
            ctx,
            raw_payload=raw,
            exception=exc,
            job_id="poisoned-1",
        )

        assert len(factory._added) == 1
        row = factory._added[0]
        assert row.function == "<unknown>"
        assert row.exception_class == "RuntimeError"
        assert row.kwargs == {"raw_payload_b64": expected_b64}
        assert row.job_id == "poisoned-1"
        assert row.traceback is not None

    @pytest.mark.asyncio
    async def test_missing_session_factory_is_noop(self):
        """No session_factory in ctx = log-and-swallow, no raise."""
        # Should not raise.
        await capture_poison_pill(
            {},
            raw_payload=b"abc",
            exception=RuntimeError("x"),
            job_id="j",
        )


# ---------------------------------------------------------------------------
# CLI: list / show / replay happy paths
# ---------------------------------------------------------------------------


def _make_dlq_row(
    *,
    function: str = "process_agent_task:entity_extraction",
    failed_at: datetime | None = None,
    replayed_at: datetime | None = None,
    kwargs: dict | None = None,
    row_id: uuid.UUID | None = None,
) -> SimpleNamespace:
    """Lightweight stand-in for the DLQJob ORM model."""
    return SimpleNamespace(
        id=row_id or uuid.uuid4(),
        job_id="job-test",
        function=function,
        args=["entity_extraction"],
        kwargs=kwargs
        or {"payload": {"episode_id": "ep-42", "text": "hi", "request_id": "req-xyz"}},
        exception_class="ValueError",
        exception_message="x",
        traceback="Traceback (most recent call last):\n  ...\nValueError: x",
        retry_count=3,
        enqueued_at=datetime.now(UTC) - timedelta(minutes=30),
        failed_at=failed_at or (datetime.now(UTC) - timedelta(hours=1)),
        replayed_at=replayed_at,
        replay_result=None,
    )


class TestCli:
    @pytest.mark.asyncio
    async def test_list_prints_rows(self, capsys):
        from scripts import dlq_replay

        rows = [_make_dlq_row(), _make_dlq_row(function="process_agent_task:notification")]

        with (
            patch.object(dlq_replay, "init_engine", MagicMock()),
            patch.object(dlq_replay, "init_session_factory", MagicMock()),
            patch.object(dlq_replay, "list_dlq_jobs", AsyncMock(return_value=rows)) as mock_list,
        ):
            # Factory returns a cm yielding a mocked session
            factory = MagicMock()
            factory.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            factory.return_value.__aexit__ = AsyncMock(return_value=False)
            dlq_replay.init_session_factory.return_value = factory

            args = dlq_replay.build_parser().parse_args(["list"])
            rc = await dlq_replay.cmd_list(args)

        assert rc == 0
        out = capsys.readouterr().out
        assert "process_agent_task:entity_extraction" in out
        assert "process_agent_task:notification" in out
        assert "2 row(s)." in out
        mock_list.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_show_dumps_full_json(self, capsys):
        from scripts import dlq_replay

        row = _make_dlq_row()

        with (
            patch.object(dlq_replay, "init_engine", MagicMock()),
            patch.object(dlq_replay, "init_session_factory", MagicMock()),
            patch.object(dlq_replay, "get_dlq_job_by_id", AsyncMock(return_value=row)),
        ):
            factory = MagicMock()
            factory.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            factory.return_value.__aexit__ = AsyncMock(return_value=False)
            dlq_replay.init_session_factory.return_value = factory

            args = dlq_replay.build_parser().parse_args(["show", str(row.id)])
            rc = await dlq_replay.cmd_show(args)

        assert rc == 0
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed["id"] == str(row.id)
        assert parsed["kwargs"]["payload"]["episode_id"] == "ep-42"
        assert "Traceback" in parsed["traceback"]

    @pytest.mark.asyncio
    async def test_replay_single_row_reenqueues_and_marks(self, capsys):
        from scripts import dlq_replay

        row = _make_dlq_row()

        session = MagicMock()
        session.commit = AsyncMock()
        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=session)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)

        pool = AsyncMock()
        pool.enqueue_job = AsyncMock()
        pool.aclose = AsyncMock()

        with (
            patch.object(dlq_replay, "init_engine", MagicMock()),
            patch.object(dlq_replay, "init_session_factory", MagicMock(return_value=factory)),
            patch.object(dlq_replay, "get_dlq_job_by_id", AsyncMock(return_value=row)),
            patch.object(dlq_replay, "mark_replayed", AsyncMock(return_value=True)) as mock_mark,
            patch("arq.connections.create_pool", AsyncMock(return_value=pool)),
            patch(
                "arq.connections.RedisSettings.from_dsn",
                MagicMock(return_value=MagicMock()),
            ),
        ):
            args = dlq_replay.build_parser().parse_args(["replay", str(row.id)])
            rc = await dlq_replay.cmd_replay(args)

        assert rc == 0
        # Job re-enqueued with original task_type + preserved request_id.
        pool.enqueue_job.assert_awaited_once()
        enqueue_args = pool.enqueue_job.await_args.args
        assert enqueue_args[0] == "process_agent_task"
        assert enqueue_args[1] == "entity_extraction"
        assert enqueue_args[2]["request_id"] == "req-xyz"
        # DLQ row marked replayed.
        mock_mark.assert_awaited_once()
        mark_kwargs = mock_mark.await_args.kwargs
        assert mark_kwargs["replay_result"] == "queued"
        assert mark_kwargs["dlq_id"] == row.id
        assert f"Replayed {row.id}: queued" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Alert cron
# ---------------------------------------------------------------------------


def _alert_settings(enabled: bool = True) -> MagicMock:
    settings = MagicMock()
    settings.dlq_alert_enabled = enabled
    settings.dlq_alert_age_threshold_hours = 24
    settings.dlq_alert_threshold_count = 1
    settings.allowed_user_ids = [12345]
    settings.github_issue_filer_enabled = False
    return settings


class TestRunDlqAlerts:
    @pytest.mark.asyncio
    async def test_skips_when_no_rows(self):
        from src.app.workers.dlq_alerts import run_dlq_alerts

        bot = AsyncMock()
        session = AsyncMock()

        @asynccontextmanager
        async def factory():
            yield session

        ctx = {
            "settings": _alert_settings(),
            "bot": bot,
            "session_factory": factory,
        }

        with patch(
            "src.app.workers.dlq_alerts.count_unreplayed_older_than",
            AsyncMock(return_value={}),
        ):
            await run_dlq_alerts(ctx)

        bot.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_when_disabled(self):
        from src.app.workers.dlq_alerts import run_dlq_alerts

        bot = AsyncMock()
        ctx = {
            "settings": _alert_settings(enabled=False),
            "bot": bot,
            "session_factory": AsyncMock(),
        }
        await run_dlq_alerts(ctx)
        bot.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fires_alert_when_rows_exist(self):
        from src.app.workers.dlq_alerts import run_dlq_alerts

        bot = AsyncMock()
        session = AsyncMock()

        @asynccontextmanager
        async def factory():
            yield session

        ctx = {
            "settings": _alert_settings(),
            "bot": bot,
            "session_factory": factory,
        }

        with patch(
            "src.app.workers.dlq_alerts.count_unreplayed_older_than",
            AsyncMock(
                return_value={
                    "process_agent_task:entity_extraction": 3,
                    "process_agent_task:notification": 1,
                }
            ),
        ):
            await run_dlq_alerts(ctx)

        bot.send_message.assert_awaited_once()
        message = bot.send_message.await_args.kwargs["text"]
        assert "Dead-Letter Queue Alert" in message
        assert "4 un-replayed" in message  # 3 + 1
        assert "entity_extraction: 3" in message
        assert "notification: 1" in message
        assert bot.send_message.await_args.kwargs["chat_id"] == 12345

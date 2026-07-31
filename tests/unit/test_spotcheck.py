"""Tests for the weekly spot-check worker + CLI."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


def _make_settings(*, enabled: bool = True, n: int = 5) -> MagicMock:
    settings = MagicMock()
    settings.spotcheck_enabled = enabled
    settings.spotcheck_n_per_week = n
    settings.spotcheck_dir = "data/evaluation/spotcheck"
    settings.allowed_user_ids = [12345]
    settings.user_timezone = "Europe/London"
    return settings


def _make_record(
    *,
    specialist: str = "diary",
    user_message: str = "Hi",
    response_content: str = "Hello!",
    score_relevance: float | None = 0.85,
) -> MagicMock:
    record = MagicMock()
    record.id = uuid4()
    record.specialist = specialist
    record.user_message = user_message
    record.response_content = response_content
    record.score_relevance = score_relevance
    record.score_actionability = 0.8
    record.score_tone = 0.9
    record.score_conciseness = 0.82
    record.created_at = datetime.now(UTC)
    return record


def _session_factory(session: AsyncMock):
    @asynccontextmanager
    async def factory():
        yield session

    return factory


# ---------------------------------------------------------------------------
# Worker: sample + file write + Telegram nudge
# ---------------------------------------------------------------------------


class TestRunWeeklySpotcheck:
    @pytest.mark.asyncio
    async def test_disabled_skips_everything(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ctx = {
            "settings": _make_settings(enabled=False),
            "session_factory": AsyncMock(),
            "bot": AsyncMock(),
        }
        from src.app.workers.spotcheck import run_weekly_spotcheck_nudge

        await run_weekly_spotcheck_nudge(ctx)
        ctx["bot"].send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_records_exits_cleanly(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        bot = AsyncMock()
        ctx = {
            "settings": _make_settings(),
            "session_factory": _session_factory(AsyncMock()),
            "bot": bot,
        }
        with patch(
            "src.app.workers.spotcheck._sample_recent",
            new_callable=AsyncMock,
            return_value=[],
        ):
            from src.app.workers.spotcheck import run_weekly_spotcheck_nudge

            await run_weekly_spotcheck_nudge(ctx)
        bot.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_writes_queue_file_and_nudges(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        bot = AsyncMock()
        records = [
            _make_record(specialist="diary"),
            _make_record(specialist="memory"),
            _make_record(specialist="project"),
        ]
        ctx = {
            "settings": _make_settings(n=3),
            "session_factory": _session_factory(AsyncMock()),
            "bot": bot,
        }
        with patch(
            "src.app.workers.spotcheck._sample_recent",
            new_callable=AsyncMock,
            return_value=records,
        ):
            from src.app.workers.spotcheck import run_weekly_spotcheck_nudge

            await run_weekly_spotcheck_nudge(ctx)

        bot.send_message.assert_awaited_once()
        call_kwargs = bot.send_message.call_args.kwargs
        assert call_kwargs["chat_id"] == 12345
        assert "spot-check" in call_kwargs["text"]

        # File written with today's date
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        queue_path = tmp_path / "data" / "evaluation" / "spotcheck" / f"{today}_queue.md"
        assert queue_path.exists()
        content = queue_path.read_text(encoding="utf-8")
        assert "Weekly Spot-check" in content
        assert "diary" in content
        assert "memory" in content
        assert "spotcheck-data" in content

    @pytest.mark.asyncio
    async def test_no_bot_still_writes_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        records = [_make_record()]
        ctx = {
            "settings": _make_settings(n=1),
            "session_factory": _session_factory(AsyncMock()),
            "bot": None,
        }
        with patch(
            "src.app.workers.spotcheck._sample_recent",
            new_callable=AsyncMock,
            return_value=records,
        ):
            from src.app.workers.spotcheck import run_weekly_spotcheck_nudge

            await run_weekly_spotcheck_nudge(ctx)
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        assert (tmp_path / "data" / "evaluation" / "spotcheck" / f"{today}_queue.md").exists()


# ---------------------------------------------------------------------------
# Queue payload extraction + helpers
# ---------------------------------------------------------------------------


class TestQueueMarkdown:
    def test_build_queue_contains_truncated_table_and_payload(self):
        from src.app.workers.spotcheck import _build_queue_markdown

        records = [_make_record(specialist="diary", user_message="x" * 200)]
        md = _build_queue_markdown(date_str="2026-04-18", records=records)
        # The markdown table portion (above the JSON payload) must be truncated.
        table_section = md.split("<!-- spotcheck-data")[0]
        assert "diary" in md
        assert "spotcheck-data" in md
        assert "x" * 200 not in table_section  # truncated in table
        # The trailing ellipsis is a signal truncation happened.
        assert "…" in table_section

    def test_truncate_removes_pipes(self):
        from src.app.workers.spotcheck import _truncate

        assert "|" not in _truncate("a | b | c", 80)


# ---------------------------------------------------------------------------
# CLI: pending / score loop / weekly-summary
# ---------------------------------------------------------------------------


def _seed_queue(tmp_path: Path, date_str: str, records: list[dict]) -> Path:
    """Write a minimal queue file matching the worker's format."""
    spotcheck_dir = tmp_path / "data" / "evaluation" / "spotcheck"
    spotcheck_dir.mkdir(parents=True, exist_ok=True)
    path = spotcheck_dir / f"{date_str}_queue.md"
    lines = [
        f"# Weekly Spot-check — {date_str}",
        "",
        "<!-- spotcheck-data",
        json.dumps(records),
        "-->",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


class TestSpotcheckCLI:
    def test_pending_lists_only_unfilled(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        _seed_queue(tmp_path, "2026-04-10", [{"id": "a", "agent": "diary"}])
        done_path = tmp_path / "data" / "evaluation" / "spotcheck" / "2026-04-03_done.md"
        queue_done = _seed_queue(tmp_path, "2026-04-03", [{"id": "b", "agent": "memory"}])
        done_path.write_text("done", encoding="utf-8")  # the "done" sibling

        from scripts.spotcheck import _cmd_pending

        _cmd_pending(MagicMock())
        captured = capsys.readouterr().out
        assert "2026-04-10_queue.md" in captured
        assert "2026-04-03_queue.md" not in captured
        # Ensure done queue was considered present
        assert queue_done.exists()

    def test_score_loop_generates_done_rows(self, monkeypatch):
        """The ✓ / ✗ / edit flow records the correct marks."""
        from scripts.spotcheck import _score_loop, _ScoreIO

        answers = iter(
            [
                "✓",  # first record
                "",  # note
                "✗",  # second
                "wrong tone",
                "edit",  # third
                "tighter",
            ],
        )

        io = _ScoreIO(reader=lambda p: next(answers), writer=lambda s: None)
        records = [
            {
                "id": "a1",
                "agent": "diary",
                "user_message": "hi",
                "response": "hello",
                "auto_mean_5pt": 4.0,
            },
            {
                "id": "b2",
                "agent": "memory",
                "user_message": "noted",
                "response": "k",
                "auto_mean_5pt": 3.5,
            },
            {
                "id": "c3",
                "agent": "review",
                "user_message": "weekly?",
                "response": "...",
                "auto_mean_5pt": 2.0,
            },
        ]
        rows = _score_loop(records, io=io)
        marks = [r["mark"] for r in rows]
        assert marks == ["✓", "✗", "edit"]
        assert rows[1]["note"] == "wrong tone"

    def test_cmd_score_writes_done_file(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        queue_path = _seed_queue(
            tmp_path,
            "2026-04-18",
            [
                {
                    "id": "aa",
                    "agent": "diary",
                    "user_message": "u",
                    "response": "r",
                    "auto_mean_5pt": 4.1,
                },
            ],
        )
        # Mock the interactive prompt to always return ✓
        from scripts import spotcheck as mod

        monkeypatch.setattr(
            mod,
            "_score_loop",
            lambda records, io=None: [
                {
                    "id": r["id"],
                    "agent": r["agent"],
                    "mark": "✓",
                    "note": "",
                    "auto_mean_5pt": r.get("auto_mean_5pt"),
                    "reviewed_at": "2026-04-18T14:00:00+00:00",
                }
                for r in records
            ],
        )

        ns = MagicMock()
        ns.queue = str(queue_path)
        mod._cmd_score(ns)

        done_path = tmp_path / "data" / "evaluation" / "spotcheck" / "2026-04-18_done.md"
        assert done_path.exists()
        content = done_path.read_text(encoding="utf-8")
        assert "DONE" in content
        assert "spotcheck-done" in content
        assert "diary" in content

    def test_weekly_summary_math(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        # Two recent done files covering diary + memory
        from scripts.spotcheck import _cmd_weekly_summary, _weekly_summary

        today = datetime.now(UTC)
        dates = [(today - timedelta(days=d)).strftime("%Y-%m-%d") for d in (2, 9)]
        for date_str in dates:
            queue_path = _seed_queue(
                tmp_path,
                date_str,
                [
                    {
                        "id": "x",
                        "agent": "diary",
                        "user_message": "q",
                        "response": "r",
                        "auto_mean_5pt": 4,
                    }
                ],
            )
            done_rows = [
                {
                    "id": "d1",
                    "agent": "diary",
                    "mark": "✓",
                    "note": "",
                    "auto_mean_5pt": 4.2,
                    "reviewed_at": "x",
                },
                {
                    "id": "d2",
                    "agent": "diary",
                    "mark": "✗",
                    "note": "tone off",
                    "auto_mean_5pt": 4.0,
                    "reviewed_at": "x",
                },
                {
                    "id": "m1",
                    "agent": "memory",
                    "mark": "edit",
                    "note": "tighten",
                    "auto_mean_5pt": 3.5,
                    "reviewed_at": "x",
                },
            ]
            done_path = queue_path.with_name(queue_path.name.replace("_queue.md", "_done.md"))
            done_path.write_text(
                "# done\n\n<!-- spotcheck-done\n" + json.dumps(done_rows) + "\n-->\n",
                encoding="utf-8",
            )

        summary = _weekly_summary(weeks=4, now=today)
        per_agent = summary["per_agent"]
        # diary: 2 files x (1 ok, 1 mismatch) = 4 total, 2 mismatches -> 50%
        assert per_agent["diary"]["total"] == 4
        assert per_agent["diary"]["mismatch"] == 2
        assert per_agent["diary"]["mismatch_rate"] == pytest.approx(0.5)
        # memory: 2 edits → 100% mismatch
        assert per_agent["memory"]["total"] == 2
        assert per_agent["memory"]["edit"] == 2
        assert per_agent["memory"]["mismatch_rate"] == pytest.approx(1.0)

        # Printing path also works
        ns = MagicMock()
        ns.weeks = 4
        _cmd_weekly_summary(ns)
        out = capsys.readouterr().out
        assert "Agent" in out
        assert "diary" in out

    def test_weekly_summary_handles_no_files(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        from scripts.spotcheck import _cmd_weekly_summary

        ns = MagicMock()
        ns.weeks = 4
        _cmd_weekly_summary(ns)
        assert "No completed spot-checks" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Sampling logic
# ---------------------------------------------------------------------------


class TestSampleRecent:
    @pytest.mark.asyncio
    async def test_sample_recent_stratifies_and_caps(self):
        from src.app.workers import spotcheck as mod

        # Build a fake session that records queries and returns canned data
        session = AsyncMock()

        # First call: agents list
        agents_result = MagicMock()
        agents_result.all.return_value = [("diary",), ("memory",), ("project",)]

        # Next calls: per-agent random record + top-up
        diary_record = _make_record(specialist="diary")
        memory_record = _make_record(specialist="memory")
        project_record = _make_record(specialist="project")
        topup_record = _make_record(specialist="diary")

        def scalars(items):
            m = MagicMock()
            m.scalars.return_value.all.return_value = items
            return m

        # Order: agents_stmt, diary_stmt, memory_stmt, project_stmt, topup_stmt
        session.execute = AsyncMock(
            side_effect=[
                agents_result,
                scalars([diary_record]),
                scalars([memory_record]),
                scalars([project_record]),
                scalars([topup_record]),
            ],
        )

        factory = _session_factory(session)
        picked = await mod._sample_recent(
            factory,
            n=4,
            now=datetime.now(UTC),
        )
        agents = {r.specialist for r in picked}
        assert {"diary", "memory", "project"} <= agents
        assert len(picked) == 4

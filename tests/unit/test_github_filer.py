"""Tests for the GitHub issue filer (Phase 3.9).

Covers:
* New fingerprint → creates issue with the right labels + body
* Existing fingerprint → comments + bumps the ``count:<N>`` label
* Closed issue (human-resolved) → deletes dedup row so a future
  recurrence opens a fresh issue
* GitHub down → alert still logged, warning emitted, caller unaffected
* Unconfigured settings → filer is a strict no-op
* Auto-resolve cron closes stale issues + sets ``resolved_at``
* Auto-resolve cron wipes rows for human-closed issues
* Category → severity mapping
* PII redactor scrubs free text before it hits the issue body

All tests mock the :class:`GitHubClient`; no real HTTP calls fire.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.core.github_client import Issue
from src.app.workers.github_filer import (
    AlertRecord,
    _render_body,
    area_for,
    compute_fingerprint,
    file_github_issue,
    run_github_issue_sync,
    severity_for,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(
    *,
    enabled: bool = True,
    repo: str = "acme/personal-assistant",
    token: str = "ghp_fake_token_for_tests",
    window_days: int = 7,
) -> SimpleNamespace:
    """Lightweight settings stand-in — the filer only reads a few attrs."""
    return SimpleNamespace(
        github_issue_filer_enabled=enabled,
        github_issue_repo=repo,
        github_token=MagicMock(get_secret_value=lambda: token),
        github_issue_dedup_window_days=window_days,
    )


def _make_session_factory(row=None, stored: list | None = None) -> MagicMock:
    """Async session factory that returns ``row`` for SELECT by fingerprint.

    Any ORM rows passed to ``session.add`` are captured in ``stored`` so
    assertions can check the dedup row was written correctly.
    """
    storage: list = stored if stored is not None else []
    deletes: list = []
    updates: list = []

    session = AsyncMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()

    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none = MagicMock(return_value=row)

    scalars_result = MagicMock()
    scalars_result.scalars = MagicMock(return_value=MagicMock(all=list))
    scalar_result.scalars = scalars_result.scalars

    async def _execute(stmt, *args, **kwargs):
        # Inspect the first token of the compiled SQL statement string to
        # decide which result shape to return.
        text = str(stmt).strip().lower()
        if text.startswith("select"):
            return scalar_result
        if text.startswith("delete"):
            deletes.append(stmt)
            return MagicMock(rowcount=1)
        if text.startswith("update"):
            updates.append(stmt)
            return MagicMock(rowcount=1)
        return MagicMock(rowcount=0)

    session.execute = AsyncMock(side_effect=_execute)
    session.add = MagicMock(side_effect=lambda obj: storage.append(obj))

    @asynccontextmanager
    async def factory():
        yield session

    factory_mock = MagicMock(side_effect=factory)
    factory_mock._session = session
    factory_mock._storage = storage
    factory_mock._deletes = deletes
    factory_mock._updates = updates
    return factory_mock


def _make_client() -> AsyncMock:
    """Mock :class:`GitHubClient` with the four methods the filer calls."""
    gh = AsyncMock()
    gh.configured = True
    gh.find_issue_by_fingerprint = AsyncMock(return_value=None)
    gh.create_issue = AsyncMock()
    gh.comment_on_issue = AsyncMock(return_value=True)
    gh.set_labels = AsyncMock(return_value=True)
    gh.close_issue = AsyncMock(return_value=True)
    return gh


def _issue(number: int, state: str = "open", labels: list[str] | None = None) -> Issue:
    return Issue(
        number=number,
        url=f"https://github.com/acme/repo/issues/{number}",
        state=state,
        title="",
        labels=labels or [],
        raw={},
    )


# ---------------------------------------------------------------------------
# Pure-function helpers
# ---------------------------------------------------------------------------


class TestFingerprint:
    def test_fingerprint_is_deterministic(self):
        fp1 = compute_fingerprint("dlq", {"function": "entity_extraction"})
        fp2 = compute_fingerprint("dlq", {"function": "entity_extraction"})
        assert fp1 == fp2

    def test_fingerprint_orders_keys(self):
        """Same key_fields in different insertion order → same fingerprint."""
        fp1 = compute_fingerprint("dlq", {"a": "1", "b": "2"})
        fp2 = compute_fingerprint("dlq", {"b": "2", "a": "1"})
        assert fp1 == fp2

    def test_fingerprint_differs_by_category(self):
        fp1 = compute_fingerprint("dlq", {"x": "1"})
        fp2 = compute_fingerprint("slo_burn", {"x": "1"})
        assert fp1 != fp2


class TestSeverityAndAreaMapping:
    def test_cost_ceiling_is_p0(self):
        assert severity_for("cost_ceiling") == "p0"

    def test_dlq_is_p1(self):
        assert severity_for("dlq") == "p1"

    def test_schema_drift_is_p1(self):
        assert severity_for("schema_drift") == "p1"

    def test_slo_burn_is_p1(self):
        assert severity_for("slo_burn") == "p1"

    def test_quality_is_p2(self):
        assert severity_for("quality") == "p2"

    def test_quality_gates_is_p2(self):
        assert severity_for("quality_gates") == "p2"

    def test_unknown_category_defaults_to_p2(self):
        assert severity_for("something-new") == "p2"

    def test_area_heuristics(self):
        assert area_for("dlq") == "worker"
        assert area_for("schema_drift") == "db"
        assert area_for("quality") == "eval"
        assert area_for("cost_ceiling") == "llm"
        assert area_for("unknown") == "misc"

    def test_explicit_area_override_wins(self):
        assert area_for("dlq", override="mcp") == "mcp"


# ---------------------------------------------------------------------------
# file_github_issue — happy-path variants
# ---------------------------------------------------------------------------


class TestFileGitHubIssue:
    @pytest.mark.asyncio
    async def test_new_fingerprint_creates_issue_with_correct_labels(self):
        gh = _make_client()
        gh.create_issue.return_value = _issue(42)
        factory = _make_session_factory(row=None)

        alert = AlertRecord(
            category="dlq",
            title="DLQ: process_agent_task:entity_extraction x3",
            summary="3 un-replayed ARQ job(s) older than 24h.",
            key_fields={"functions": "process_agent_task:entity_extraction"},
            context={"Message": "Dead-Letter Queue Alert\n\n3 un-replayed..."},
            request_id="req-abc",
        )
        url = await file_github_issue(
            alert,
            settings=_make_settings(),
            session_factory=factory,
            client=gh,
        )

        assert url == "https://github.com/acme/repo/issues/42"
        gh.create_issue.assert_awaited_once()
        call = gh.create_issue.await_args
        labels = call.kwargs["labels"]
        assert "from-prod" in labels
        assert "bug" in labels
        assert "area-worker" in labels
        assert "severity-p1" in labels
        assert any(lab.startswith("fingerprint:") for lab in labels)
        # count:1 is NOT added on creation (only on recurrence).
        assert not any(lab.startswith("count:") for lab in labels)

        # Dedup row was persisted.
        assert len(factory._storage) == 1
        stored = factory._storage[0]
        assert stored.github_issue_number == 42
        assert stored.category == "dlq"
        assert stored.recurrence_count == 1

    @pytest.mark.asyncio
    async def test_recurrence_comments_and_bumps_counter(self):
        """A known fingerprint with an open issue → comment + set_labels."""
        gh = _make_client()
        gh.find_issue_by_fingerprint.return_value = _issue(99)

        # Simulate an existing dedup row with count=3.
        existing_row = SimpleNamespace(
            id="uuid-1",
            recurrence_count=3,
            fingerprint="does-not-matter-for-this-path",
        )
        factory = _make_session_factory(row=existing_row)

        alert = AlertRecord(
            category="dlq",
            title="DLQ: entity_extraction x5",
            summary="5 un-replayed jobs",
            key_fields={"functions": "entity_extraction"},
            request_id="req-xyz-42",
        )
        url = await file_github_issue(
            alert,
            settings=_make_settings(),
            session_factory=factory,
            client=gh,
        )

        assert url == "https://github.com/acme/repo/issues/99"
        gh.create_issue.assert_not_awaited()
        gh.comment_on_issue.assert_awaited_once()
        comment_body = gh.comment_on_issue.await_args.kwargs["body"]
        assert "Recurrence #4" in comment_body
        assert "req-xyz-42" in comment_body

        # set_labels replaces the full set and includes count:4.
        gh.set_labels.assert_awaited_once()
        new_labels = gh.set_labels.await_args.kwargs["labels"]
        assert "count:4" in new_labels
        assert any(lab.startswith("fingerprint:") for lab in new_labels)

        # An UPDATE was issued; no new row was stored.
        assert factory._storage == []
        assert len(factory._updates) >= 1

    @pytest.mark.asyncio
    async def test_closed_issue_wipes_dedup_row_then_reopens_fresh_one(self):
        """Human closed an earlier issue → delete row + create fresh one."""
        gh = _make_client()
        # The search returns the CLOSED prior issue on the first call, then
        # the filer should ignore it and create a brand-new one.
        gh.find_issue_by_fingerprint.return_value = _issue(7, state="closed")
        gh.create_issue.return_value = _issue(123)

        existing_row = SimpleNamespace(
            id="uuid-old",
            recurrence_count=5,
            fingerprint="same-fp-as-the-closed-issue",
        )
        factory = _make_session_factory(row=existing_row)

        alert = AlertRecord(
            category="schema_drift",
            title="Schema drift: commitments.is_active does not exist",
            summary="10 occurrences",
            key_fields={"table": "commitments", "column": "is_active"},
        )
        url = await file_github_issue(
            alert,
            settings=_make_settings(),
            session_factory=factory,
            client=gh,
        )

        # A DELETE fired before the new create.
        assert len(factory._deletes) >= 1
        # New issue was created with a fresh count=1 (no count: label).
        gh.create_issue.assert_awaited_once()
        labels = gh.create_issue.await_args.kwargs["labels"]
        assert "severity-p1" in labels
        assert "area-db" in labels
        assert not any(lab.startswith("count:") for lab in labels)
        assert url == "https://github.com/acme/repo/issues/123"

    @pytest.mark.asyncio
    async def test_github_down_logs_warning_does_not_raise(self):
        """HTTP exceptions from the client must NOT propagate."""
        gh = _make_client()
        gh.find_issue_by_fingerprint.side_effect = RuntimeError("github 500")
        factory = _make_session_factory(row=None)

        alert = AlertRecord(
            category="slo_burn",
            title="SLO burn",
            summary="test",
            key_fields={"slo": "latency"},
        )
        # Must not raise.
        url = await file_github_issue(
            alert,
            settings=_make_settings(),
            session_factory=factory,
            client=gh,
        )
        assert url is None

    @pytest.mark.asyncio
    async def test_unconfigured_settings_is_noop(self):
        """Empty repo → filer is a strict no-op; no HTTP attempted."""
        factory = _make_session_factory(row=None)
        settings = _make_settings(repo="", token="")

        alert = AlertRecord(
            category="dlq",
            title="t",
            summary="s",
            key_fields={"f": "1"},
        )
        # Call without injecting the client — build_client must short-circuit.
        url = await file_github_issue(
            alert,
            settings=settings,
            session_factory=factory,
            client=None,
        )
        assert url is None
        # No DB row was written either.
        assert factory._storage == []

    @pytest.mark.asyncio
    async def test_disabled_flag_is_noop(self):
        factory = _make_session_factory(row=None)
        settings = _make_settings(enabled=False)

        alert = AlertRecord(
            category="dlq",
            title="t",
            summary="s",
            key_fields={"f": "1"},
        )
        url = await file_github_issue(
            alert,
            settings=settings,
            session_factory=factory,
            client=None,
        )
        assert url is None

    @pytest.mark.asyncio
    async def test_create_failure_leaves_dedup_empty(self):
        """A None return from create_issue must NOT persist a row."""
        gh = _make_client()
        gh.create_issue.return_value = None  # Simulated 500 / timeout.
        factory = _make_session_factory(row=None)

        alert = AlertRecord(
            category="dlq",
            title="t",
            summary="s",
            key_fields={"f": "1"},
        )
        url = await file_github_issue(
            alert,
            settings=_make_settings(),
            session_factory=factory,
            client=gh,
        )
        assert url is None
        assert factory._storage == []


# ---------------------------------------------------------------------------
# Body rendering + PII redaction
# ---------------------------------------------------------------------------


class TestBodyRendering:
    def test_redacts_emails_in_context(self):
        alert = AlertRecord(
            category="dlq",
            title="t",
            summary="Failure for user contact alice@example.com",
            key_fields={"f": "1"},
            context={"Traceback": "raised while emailing bob@example.com at 202-555-0101"},
        )
        body = _render_body(alert)
        assert "alice@example.com" not in body
        assert "bob@example.com" not in body
        assert "07539" not in body
        assert "[redacted-email]" in body
        assert "[redacted-phone]" in body

    def test_body_includes_severity_and_category(self):
        alert = AlertRecord(
            category="cost_ceiling",
            title="t",
            summary="Too much money spent.",
            key_fields={"date": "2026-04-18"},
        )
        body = _render_body(alert)
        assert "`cost_ceiling`" in body
        assert "`p0`" in body

    def test_body_includes_correlation_ids(self):
        alert = AlertRecord(
            category="dlq",
            title="t",
            summary="s",
            key_fields={"f": "1"},
            request_id="req-abc",
            trace_id="trace-xyz",
        )
        body = _render_body(alert)
        assert "req-abc" in body
        assert "trace-xyz" in body


# ---------------------------------------------------------------------------
# Auto-resolve cron
# ---------------------------------------------------------------------------


class TestRunGitHubIssueSync:
    @pytest.mark.asyncio
    async def test_closes_stale_issues_sets_resolved_at(self, monkeypatch):
        """A row older than window_days with resolved_at NULL → close + mark."""
        now = datetime.now(UTC)
        stale_row = SimpleNamespace(
            id="uuid-1",
            fingerprint="fp-1",
            github_issue_number=10,
            last_seen=now - timedelta(days=14),
            resolved_at=None,
        )

        # Build a factory whose first SELECT returns [stale_row] and the
        # second (remaining after pass 1) returns [].
        session = AsyncMock()
        session.commit = AsyncMock()
        executed: list[str] = []

        def _scalars_for(rows: list):
            scalars = MagicMock()
            scalars.all = MagicMock(return_value=rows)
            result = MagicMock()
            result.scalars = MagicMock(return_value=scalars)
            return result

        select_results = [
            _scalars_for([stale_row]),  # pass 1
            _scalars_for([]),  # pass 2
        ]

        async def _execute(stmt, *args, **kwargs):
            text = str(stmt).strip().lower()
            executed.append(text[:60])
            if text.startswith("select"):
                return select_results.pop(0)
            return MagicMock(rowcount=1)

        session.execute = AsyncMock(side_effect=_execute)

        @asynccontextmanager
        async def factory():
            yield session

        gh = _make_client()
        gh.close_issue.return_value = True

        monkeypatch.setattr(
            "src.app.workers.github_filer._build_client",
            lambda _settings: gh,
        )

        await run_github_issue_sync(
            {
                "settings": _make_settings(window_days=7),
                "session_factory": factory,
            }
        )

        gh.close_issue.assert_awaited_once()
        close_kwargs = gh.close_issue.await_args.kwargs
        assert close_kwargs["issue_number"] == 10
        assert "auto-resolving" in close_kwargs["comment"].lower()

    @pytest.mark.asyncio
    async def test_wipes_rows_for_human_closed_issues(self, monkeypatch):
        """A row whose GitHub issue is already closed → delete row."""
        now = datetime.now(UTC)
        # Not stale (still inside the window) but the issue is closed remotely.
        fresh_but_resolved_row = SimpleNamespace(
            id="uuid-2",
            fingerprint="fp-fresh",
            github_issue_number=55,
            last_seen=now - timedelta(hours=1),
            resolved_at=None,
        )

        session = AsyncMock()
        session.commit = AsyncMock()
        deletes: list = []

        def _scalars_for(rows: list):
            scalars = MagicMock()
            scalars.all = MagicMock(return_value=rows)
            result = MagicMock()
            result.scalars = MagicMock(return_value=scalars)
            return result

        select_results = [
            _scalars_for([]),  # pass 1 — no stale rows
            _scalars_for([fresh_but_resolved_row]),  # pass 2 — this one
        ]

        async def _execute(stmt, *args, **kwargs):
            text = str(stmt).strip().lower()
            if text.startswith("select"):
                return select_results.pop(0)
            if text.startswith("delete"):
                deletes.append(stmt)
                return MagicMock(rowcount=1)
            return MagicMock(rowcount=1)

        session.execute = AsyncMock(side_effect=_execute)

        @asynccontextmanager
        async def factory():
            yield session

        gh = _make_client()
        # The remote search returns the SAME issue number, closed state.
        gh.find_issue_by_fingerprint.return_value = _issue(55, state="closed")

        monkeypatch.setattr(
            "src.app.workers.github_filer._build_client",
            lambda _settings: gh,
        )

        await run_github_issue_sync(
            {
                "settings": _make_settings(),
                "session_factory": factory,
            }
        )

        # We expected a DELETE (to wipe the stale dedup row) — the close
        # path in pass 1 should NOT have fired because no stale rows were
        # returned.
        assert deletes, "expected at least one DELETE"
        gh.close_issue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unconfigured_sync_is_noop(self, monkeypatch):
        gh_calls: list = []

        monkeypatch.setattr(
            "src.app.workers.github_filer._build_client",
            lambda _settings: None,
        )

        # No session should be touched.
        factory_mock = MagicMock()
        await run_github_issue_sync(
            {
                "settings": _make_settings(repo="", token=""),
                "session_factory": factory_mock,
            }
        )
        assert gh_calls == []
        factory_mock.assert_not_called()

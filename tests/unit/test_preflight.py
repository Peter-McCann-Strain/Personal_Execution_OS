"""Tests for startup preflight validation."""

from __future__ import annotations

import builtins
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.core.preflight import (
    PreflightCheck,
    _check_assistant_native_replays,
    _check_database_extensions,
    _check_evaluation_assets,
    _check_export_directory,
    _check_optional_integrations,
    _check_provider_configuration,
    _check_redis_connectivity,
    _check_runtime_policies,
    run_startup_preflight,
    summarize_preflight_status,
)


def _make_settings() -> MagicMock:
    settings = MagicMock()
    settings.app_env = "test"
    settings.evaluation_export_dir = "data/evaluation/exports"
    settings.anthropic_api_key = SimpleNamespace(get_secret_value=lambda: "test-anthropic-key")
    settings.database_url = SimpleNamespace(get_secret_value=lambda: "postgresql://db")
    settings.chat_api_key = SimpleNamespace(get_secret_value=lambda: "test-chat-key")
    settings.llm_configured = True
    settings.google_configured = False
    settings.tavily_configured = False
    settings.telegram_configured = False
    settings.sentry_configured = False
    settings.posthog_configured = False
    settings.workflow_live_runtime_enabled = True
    settings.auto_judge_enabled = True
    settings.quality_gates_alerts_enabled = True
    settings.session_maintenance_enabled = True
    settings.assistant_native_replay_eval_enabled = True
    settings.assistant_native_replay_pass_rate_target = 1.0
    settings.assistant_native_replay_baseline_lift_target = 0.5
    settings.startup_preflight_fail_fast = False
    settings.redis_url = SimpleNamespace(get_secret_value=lambda: "redis://localhost:6379")
    return settings


def test_summarize_preflight_status_ok_warn_fail():
    assert summarize_preflight_status([PreflightCheck(name="a", status="ok", message="ok")]) == "ok"
    assert (
        summarize_preflight_status(
            [PreflightCheck(name="a", status="warn", message="warn", required=False)]
        )
        == "warn"
    )
    assert (
        summarize_preflight_status([PreflightCheck(name="a", status="fail", message="fail")])
        == "fail"
    )


@pytest.mark.asyncio
async def test_run_startup_preflight_skips_runtime_checks_in_test_mode():
    settings = _make_settings()

    report = await run_startup_preflight(
        settings=settings,
        include_runtime_checks=False,
    )

    assert report.status in {"ok", "warn"}
    assert any(check.name == "evaluation_assets" for check in report.checks)
    assert any(check.status == "skipped" for check in report.checks)


@pytest.mark.asyncio
async def test_run_startup_preflight_fail_fast_raises(monkeypatch: pytest.MonkeyPatch):
    from src.app.core import preflight as preflight_module

    settings = _make_settings()
    settings.startup_preflight_fail_fast = True

    monkeypatch.setattr(
        preflight_module,
        "_check_evaluation_assets",
        lambda: PreflightCheck(
            name="evaluation_assets",
            status="fail",
            message="broken assets",
        ),
    )

    with pytest.raises(RuntimeError, match="Startup preflight failed"):
        await run_startup_preflight(
            settings=settings,
            include_runtime_checks=False,
        )


@pytest.mark.asyncio
async def test_run_startup_preflight_production_fails_fast_by_default(
    monkeypatch: pytest.MonkeyPatch,
):
    from src.app.core import preflight as preflight_module

    settings = _make_settings()
    settings.app_env = "production"
    settings.startup_preflight_fail_fast = False

    monkeypatch.setattr(
        preflight_module,
        "_check_evaluation_assets",
        lambda: PreflightCheck(
            name="evaluation_assets",
            status="fail",
            message="broken assets",
        ),
    )

    with pytest.raises(RuntimeError, match="Startup preflight failed"):
        await run_startup_preflight(
            settings=settings,
            include_runtime_checks=False,
        )


def test_check_evaluation_assets_reports_failure(monkeypatch: pytest.MonkeyPatch):
    from src.app.core import preflight as preflight_module

    monkeypatch.setattr(
        preflight_module,
        "validate_evaluation_assets",
        lambda: ["missing rubric"],
    )

    check = _check_evaluation_assets()

    assert check.status == "fail"
    assert check.details["errors"] == ["missing rubric"]


def test_check_assistant_native_replays_ok(monkeypatch: pytest.MonkeyPatch):
    from src.app.core import preflight as preflight_module

    monkeypatch.setattr(
        preflight_module,
        "validate_assistant_native_eval_assets",
        list,
    )
    monkeypatch.setattr(
        preflight_module,
        "evaluate_assistant_native_replays",
        lambda: SimpleNamespace(
            pass_rate=1.0,
            baseline_lift=0.8,
            failing_case_ids=[],
            case_count=6,
        ),
    )

    check = _check_assistant_native_replays(_make_settings())

    assert check.status == "ok"
    assert check.details["pass_rate"] == 1.0


def test_check_assistant_native_replays_reports_asset_failure(
    monkeypatch: pytest.MonkeyPatch,
):
    from src.app.core import preflight as preflight_module

    monkeypatch.setattr(
        preflight_module,
        "validate_assistant_native_eval_assets",
        lambda: ["missing assistant-native dataset"],
    )

    check = _check_assistant_native_replays(_make_settings())

    assert check.status == "fail"
    assert check.details["errors"] == ["missing assistant-native dataset"]


def test_check_export_directory_creates_path(tmp_path: Path):
    settings = _make_settings()
    settings.evaluation_export_dir = str(tmp_path / "exports")

    check = _check_export_directory(settings)

    assert check.status == "ok"
    assert (tmp_path / "exports").is_dir()


def test_check_export_directory_falls_back_for_mock_like_value(tmp_path: Path):
    settings = _make_settings()
    settings.evaluation_export_dir = "<MagicMock name='mock.evaluation_export_dir'>"
    fallback = Path("data/evaluation/exports")
    fallback_existed = fallback.exists()

    check = _check_export_directory(settings)

    assert check.status == "ok"
    assert check.details["path"] == fallback.as_posix()
    assert fallback.is_dir()

    if not fallback_existed:
        fallback.rmdir()


def test_check_provider_configuration_ok_with_missing_optional():
    settings = _make_settings()

    check = _check_provider_configuration(settings)

    assert check.status == "warn"
    assert check.details["missing_required"] == []
    assert set(check.details["missing_optional"]) == {
        "google_workspace",
        "tavily",
        "telegram",
        "sentry",
        "posthog",
    }


def test_check_provider_configuration_fails_when_required_missing():
    settings = _make_settings()
    settings.database_url = SimpleNamespace(get_secret_value=lambda: "")
    settings.redis_url = SimpleNamespace(get_secret_value=lambda: "")

    check = _check_provider_configuration(settings)

    assert check.status == "fail"
    assert set(check.details["missing_required"]) == {"database", "redis"}


def test_check_runtime_policies_warns_when_flags_disabled():
    settings = _make_settings()
    settings.continuity_runtime_enabled = False
    settings.notes_workspace_enabled = False

    check = _check_runtime_policies(settings)

    assert check.status == "warn"
    assert set(check.details["disabled_flags"]) == {
        "continuity_runtime_enabled",
        "notes_workspace_enabled",
    }


def test_check_runtime_policies_ok_when_flags_enabled():
    settings = _make_settings()

    check = _check_runtime_policies(settings)

    assert check.status == "ok"
    assert check.details["disabled_flags"] == []


@pytest.mark.asyncio
async def test_check_optional_integrations_reports_direct_configuration():
    settings = _make_settings()
    settings.google_configured = True
    settings.tavily_configured = True

    check = await _check_optional_integrations(settings)

    assert check.status == "ok"
    assert check.details["configured_integrations"] == [
        "google_calendar",
        "gmail",
        "tavily",
    ]


class _FakeResult:
    def __init__(self, values: list[str]):
        self._values = values

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[str]:
        return self._values


class _FakeSessionContext:
    def __init__(self, session: object):
        self.session = session

    async def __aenter__(self) -> object:
        return self.session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


@pytest.mark.asyncio
async def test_check_database_extensions_skips_without_session_factory():
    check = await _check_database_extensions(None)

    assert check.status == "skipped"


@pytest.mark.asyncio
async def test_check_database_extensions_warns_on_query_error():
    session = MagicMock()
    session.execute = AsyncMock(side_effect=RuntimeError("query failed"))

    def session_factory():
        return _FakeSessionContext(session)

    check = await _check_database_extensions(session_factory)

    assert check.status == "warn"
    assert "query failed" in check.details["error"]


@pytest.mark.asyncio
async def test_check_database_extensions_warns_when_extensions_missing():
    session = MagicMock()
    session.execute = AsyncMock(return_value=_FakeResult(["vector"]))

    def session_factory():
        return _FakeSessionContext(session)

    check = await _check_database_extensions(session_factory)

    assert check.status == "warn"
    assert check.details["missing"] == ["pg_trgm"]


@pytest.mark.asyncio
async def test_check_database_extensions_ok_when_all_present():
    session = MagicMock()
    session.execute = AsyncMock(return_value=_FakeResult(["pg_trgm", "vector"]))

    def session_factory():
        return _FakeSessionContext(session)

    check = await _check_database_extensions(session_factory)

    assert check.status == "ok"
    assert check.details["installed"] == ["pg_trgm", "vector"]


@pytest.mark.asyncio
async def test_check_redis_connectivity_warns_when_import_missing(
    monkeypatch: pytest.MonkeyPatch,
):
    original_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "redis.asyncio":
            raise ImportError("redis missing")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    check = await _check_redis_connectivity(_make_settings())

    assert check.status == "warn"
    assert "not installed" in check.message


def _install_fake_redis(monkeypatch: pytest.MonkeyPatch, client: object) -> None:
    redis_module = ModuleType("redis")
    redis_async_module = ModuleType("redis.asyncio")
    redis_async_module.from_url = lambda *args, **kwargs: client
    redis_module.asyncio = redis_async_module
    monkeypatch.setitem(sys.modules, "redis", redis_module)
    monkeypatch.setitem(sys.modules, "redis.asyncio", redis_async_module)


@pytest.mark.asyncio
async def test_check_redis_connectivity_warns_on_missing_url():
    settings = _make_settings()
    settings.redis_url = SimpleNamespace(get_secret_value=lambda: "")

    check = await _check_redis_connectivity(settings)

    assert check.status == "warn"
    assert "unavailable" in check.message


@pytest.mark.asyncio
async def test_check_redis_connectivity_warns_on_ping_failure(
    monkeypatch: pytest.MonkeyPatch,
):
    settings = _make_settings()

    class _FailingRedisClient:
        async def ping(self) -> bool:
            raise RuntimeError("redis down")

        async def aclose(self) -> None:
            return None

    client = _FailingRedisClient()
    _install_fake_redis(monkeypatch, client)

    check = await _check_redis_connectivity(settings)

    assert check.status == "warn"
    assert "redis down" in check.details["error"]


@pytest.mark.asyncio
async def test_check_redis_connectivity_ok_on_success(monkeypatch: pytest.MonkeyPatch):
    settings = _make_settings()

    class _FakeRedisClient:
        async def ping(self) -> bool:
            return True

        async def aclose(self) -> None:
            return None

    _install_fake_redis(monkeypatch, _FakeRedisClient())

    check = await _check_redis_connectivity(settings)

    assert check.status == "ok"
    assert "verified" in check.message


@pytest.mark.asyncio
async def test_check_redis_connectivity_fails_on_false_ping(monkeypatch: pytest.MonkeyPatch):
    settings = _make_settings()
    settings.app_env = "production"

    class _FalseRedisClient:
        async def ping(self) -> bool:
            return False

        async def aclose(self) -> None:
            return None

    _install_fake_redis(monkeypatch, _FalseRedisClient())

    check = await _check_redis_connectivity(settings)

    assert check.status == "fail"
    assert "returned false" in check.message


@pytest.mark.asyncio
async def test_run_startup_preflight_includes_runtime_checks(monkeypatch: pytest.MonkeyPatch):
    from src.app.core import preflight as preflight_module

    settings = _make_settings()
    settings.app_env = "production"

    monkeypatch.setattr(
        preflight_module,
        "_check_database_extensions",
        AsyncMock(
            return_value=PreflightCheck(
                name="database_extensions",
                status="ok",
                message="ok",
                required=False,
            )
        ),
    )
    monkeypatch.setattr(
        preflight_module,
        "_check_redis_connectivity",
        AsyncMock(
            return_value=PreflightCheck(
                name="redis_connectivity",
                status="warn",
                message="warn",
                required=False,
            )
        ),
    )

    report = await run_startup_preflight(
        settings=settings,
        session_factory=MagicMock(),
        include_runtime_checks=True,
    )

    assert report.status == "warn"
    assert any(check.name == "database_extensions" for check in report.checks)
    assert any(check.name == "redis_connectivity" for check in report.checks)


@pytest.mark.asyncio
async def test_run_startup_preflight_uses_default_runtime_skip_when_env_is_test(
    monkeypatch: pytest.MonkeyPatch,
):
    from src.app.core import preflight as preflight_module

    settings = _make_settings()
    settings.app_env = "test"

    monkeypatch.setattr(
        preflight_module,
        "_check_evaluation_assets",
        lambda: PreflightCheck(name="evaluation_assets", status="ok", message="ok"),
    )
    monkeypatch.setattr(
        preflight_module,
        "_check_export_directory",
        lambda _settings: PreflightCheck(name="evaluation_export_dir", status="ok", message="ok"),
    )
    monkeypatch.setattr(
        preflight_module,
        "_check_optional_integrations",
        AsyncMock(
            return_value=PreflightCheck(
                name="optional_integrations",
                status="ok",
                message="ok",
                required=False,
            )
        ),
    )

    report = await run_startup_preflight(settings=settings)

    assert report.status == "warn"
    assert any(check.name == "runtime_connectivity" for check in report.checks)

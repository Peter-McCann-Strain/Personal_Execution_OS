"""Startup preflight validation for production readiness."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.app.config import Settings, get_settings
from src.app.core.assistant_native_evals import (
    ASSISTANT_NATIVE_EVAL_DATASET_PATH,
    evaluate_assistant_native_replays,
    validate_assistant_native_eval_assets,
)
from src.app.core.evaluation_registry import EVALUATION_ROOT, validate_evaluation_assets

logger = structlog.get_logger()

PreflightStatus = Literal["ok", "warn", "fail", "skipped"]


class PreflightCheck(BaseModel):
    """One preflight validation result."""

    name: str
    status: PreflightStatus
    message: str
    required: bool = True
    details: dict[str, Any] = Field(default_factory=dict)


class PreflightReport(BaseModel):
    """Full startup preflight report."""

    status: Literal["ok", "warn", "fail"]
    generated_at: datetime
    checks: list[PreflightCheck] = Field(default_factory=list)


def summarize_preflight_status(checks: list[PreflightCheck]) -> Literal["ok", "warn", "fail"]:
    """Roll up a set of checks into one overall status."""
    if any(check.status == "fail" and check.required for check in checks):
        return "fail"
    if any(check.status == "warn" for check in checks):
        return "warn"
    return "ok"


def _check_prompt_hashes(settings: Settings) -> PreflightCheck:
    """Fail fast if any prompt content drifted without a ``PROMPT_VERSION`` bump.

    Controlled by ``settings.expected_prompt_hashes`` — an empty map means
    "dev mode, skip validation". In production populate this map with the
    live hashes after every prompt-version bump. Dump current values via::

        python -c "from src.app.agents.prompts import PROMPT_CONTENT_HASHES; \\
            import json; print(json.dumps(PROMPT_CONTENT_HASHES, indent=2))"
    """
    from src.app.agents.prompts import PROMPT_CONTENT_HASHES, validate_prompt_hashes

    expected = getattr(settings, "expected_prompt_hashes", {}) or {}
    if not expected:
        return PreflightCheck(
            name="prompt_hashes",
            status="skipped",
            required=False,
            message="expected_prompt_hashes is empty — skipping validation (dev mode)",
            details={"live_hashes": PROMPT_CONTENT_HASHES},
        )
    drift = validate_prompt_hashes(expected, strict=False)
    if drift:
        return PreflightCheck(
            name="prompt_hashes",
            status="fail",
            required=True,
            message="Prompt content drift detected — bump PROMPT_VERSION.",
            details={
                "drift": drift,
                "live_hashes": PROMPT_CONTENT_HASHES,
                "expected_hashes": expected,
            },
        )
    return PreflightCheck(
        name="prompt_hashes",
        status="ok",
        message=f"All {len(expected)} prompt hashes match expected values",
        details={"agents_checked": sorted(expected.keys())},
    )


def _check_evaluation_assets() -> PreflightCheck:
    """Ensure rubric/dataset assets exist and align with runtime contracts."""
    errors = validate_evaluation_assets()
    if errors:
        return PreflightCheck(
            name="evaluation_assets",
            status="fail",
            message="Evaluation assets are incomplete or inconsistent",
            details={"errors": errors},
        )
    return PreflightCheck(
        name="evaluation_assets",
        status="ok",
        message="Evaluation rubrics and datasets are present",
        details={"root": EVALUATION_ROOT.as_posix()},
    )


def _check_assistant_native_replays(settings: Settings) -> PreflightCheck:
    """Ensure deterministic assistant-native replay coverage is present and passing."""
    if not bool(getattr(settings, "assistant_native_replay_eval_enabled", True)):
        return PreflightCheck(
            name="assistant_native_replays",
            status="warn",
            required=False,
            message="Assistant-native replay evaluation is disabled",
            details={"dataset": ASSISTANT_NATIVE_EVAL_DATASET_PATH.as_posix()},
        )

    errors = validate_assistant_native_eval_assets()
    if errors:
        return PreflightCheck(
            name="assistant_native_replays",
            status="fail",
            message="Assistant-native replay assets are incomplete or inconsistent",
            details={
                "dataset": ASSISTANT_NATIVE_EVAL_DATASET_PATH.as_posix(),
                "errors": errors,
            },
        )

    result = evaluate_assistant_native_replays()
    pass_rate_target = float(getattr(settings, "assistant_native_replay_pass_rate_target", 1.0))
    baseline_lift_target = float(
        getattr(settings, "assistant_native_replay_baseline_lift_target", 0.5)
    )
    if result.pass_rate < pass_rate_target or result.baseline_lift < baseline_lift_target:
        return PreflightCheck(
            name="assistant_native_replays",
            status="fail",
            message="Assistant-native replay suite is below world-class thresholds",
            details={
                "dataset": ASSISTANT_NATIVE_EVAL_DATASET_PATH.as_posix(),
                "pass_rate": result.pass_rate,
                "pass_rate_target": pass_rate_target,
                "baseline_lift": result.baseline_lift,
                "baseline_lift_target": baseline_lift_target,
                "failing_case_ids": result.failing_case_ids,
            },
        )

    return PreflightCheck(
        name="assistant_native_replays",
        status="ok",
        message="Assistant-native replay suite is passing",
        details={
            "dataset": ASSISTANT_NATIVE_EVAL_DATASET_PATH.as_posix(),
            "pass_rate": result.pass_rate,
            "baseline_lift": result.baseline_lift,
            "case_count": result.case_count,
        },
    )


def _check_export_directory(settings: Settings) -> PreflightCheck:
    """Ensure the evaluation export directory exists."""
    raw_export_dir = getattr(settings, "evaluation_export_dir", "data/evaluation/exports")
    if isinstance(raw_export_dir, Path):
        export_dir = raw_export_dir
    elif isinstance(raw_export_dir, str):
        candidate = raw_export_dir.strip()
        if not candidate or candidate.startswith("<MagicMock"):
            export_dir = Path("data/evaluation/exports")
        else:
            export_dir = Path(candidate)
    else:
        export_dir = Path("data/evaluation/exports")
    export_dir.mkdir(parents=True, exist_ok=True)
    return PreflightCheck(
        name="evaluation_export_dir",
        status="ok",
        message="Evaluation export directory is ready",
        details={"path": export_dir.as_posix()},
    )


def _is_present(value: Any) -> bool:
    """Return True when a config value contains a non-placeholder value."""
    if value is None:
        return False
    if hasattr(value, "get_secret_value"):
        value = value.get_secret_value()
    if isinstance(value, str):
        stripped = value.strip()
        return bool(stripped and not stripped.startswith("PLACEHOLDER"))
    return bool(value)


def _check_provider_configuration(settings: Settings) -> PreflightCheck:
    """Summarize core and optional external provider readiness from configuration."""
    required = {
        "database": _is_present(settings.database_url),
        "redis": _is_present(settings.redis_url),
    }
    optional = {
        "llm": bool(getattr(settings, "llm_configured", False)),
        "local_owner_api_key": _is_present(settings.chat_api_key),
        "google_workspace": bool(getattr(settings, "google_configured", False)),
        "tavily": bool(getattr(settings, "tavily_configured", False)),
        "telegram": bool(getattr(settings, "telegram_configured", False)),
        "sentry": bool(getattr(settings, "sentry_configured", False)),
        "posthog": bool(getattr(settings, "posthog_configured", False)),
    }

    missing_required = [name for name, configured in required.items() if not configured]
    missing_optional = [name for name, configured in optional.items() if not configured]

    if missing_required:
        return PreflightCheck(
            name="provider_configuration",
            status="fail",
            message="Required provider configuration is incomplete",
            details={
                "required": required,
                "optional": optional,
                "missing_required": missing_required,
                "missing_optional": missing_optional,
            },
        )

    return PreflightCheck(
        name="provider_configuration",
        status="warn" if missing_optional else "ok",
        required=False,
        message=(
            "Core provider configuration is present; optional capabilities are unavailable"
            if missing_optional
            else "Core and optional provider configuration is present"
        ),
        details={
            "required": required,
            "optional": optional,
            "missing_required": [],
            "missing_optional": missing_optional,
        },
    )


def _check_runtime_policies(settings: Settings) -> PreflightCheck:
    """Report only core local product surfaces, not opt-in automation flags."""
    policy_flags = {
        "continuity_runtime_enabled": bool(getattr(settings, "continuity_runtime_enabled", True)),
        "project_draft_runtime_enabled": bool(
            getattr(settings, "project_draft_runtime_enabled", True)
        ),
        "notes_workspace_enabled": bool(getattr(settings, "notes_workspace_enabled", True)),
        "content_factory_enabled": bool(getattr(settings, "content_factory_enabled", True)),
    }
    disabled = [name for name, enabled in policy_flags.items() if not enabled]
    app_env = getattr(settings, "app_env", "unknown")

    if disabled:
        return PreflightCheck(
            name="runtime_policies",
            status="warn",
            required=False,
            message="Core runtime reliability policies are not fully enabled",
            details={
                "flags": policy_flags,
                "disabled_flags": disabled,
                "app_env": app_env,
            },
        )

    return PreflightCheck(
        name="runtime_policies",
        status="ok",
        required=False,
        message="Core runtime reliability policies are enabled",
        details={
            "flags": policy_flags,
            "disabled_flags": [],
            "app_env": app_env,
        },
    )


async def _check_optional_integrations(
    settings: Settings,
) -> PreflightCheck:
    """Summarize optional integration configuration without MCP coupling."""
    configured_integrations: list[str] = []
    if bool(getattr(settings, "google_configured", False)):
        configured_integrations.extend(["google_calendar", "gmail"])
    if bool(getattr(settings, "tavily_configured", False)):
        configured_integrations.append("tavily")

    return PreflightCheck(
        name="optional_integrations",
        status="ok",
        required=False,
        message="Optional integration configuration loaded",
        details={
            "configured_integrations": configured_integrations,
            "telegram_configured": bool(getattr(settings, "telegram_configured", False)),
            "sentry_configured": bool(getattr(settings, "sentry_configured", False)),
            "posthog_configured": bool(getattr(settings, "posthog_configured", False)),
        },
    )


async def _check_database_extensions(
    session_factory: async_sessionmaker[AsyncSession] | None,
) -> PreflightCheck:
    """Verify the database has the recommended extensions for retrieval/search."""
    if session_factory is None:
        return PreflightCheck(
            name="database_extensions",
            status="skipped",
            required=False,
            message="Database extension checks skipped without a session factory",
        )

    try:
        async with session_factory() as session:
            result = await session.execute(
                text("SELECT extname FROM pg_extension WHERE extname IN ('vector', 'pg_trgm')")
            )
            extensions = sorted(result.scalars().all())
    except Exception as exc:
        logger.warning(
            "preflight_database_extensions_failed",
            error_class=type(exc).__name__,
        )
        return PreflightCheck(
            name="database_extensions",
            status="warn",
            required=False,
            message="Could not verify database extensions",
            details={"error": str(exc)},
        )

    missing = [ext for ext in ("vector", "pg_trgm") if ext not in extensions]
    if missing:
        return PreflightCheck(
            name="database_extensions",
            status="warn",
            required=False,
            message="Database is missing recommended extensions",
            details={"installed": extensions, "missing": missing},
        )

    return PreflightCheck(
        name="database_extensions",
        status="ok",
        required=False,
        message="Database extensions are installed",
        details={"installed": extensions},
    )


async def _check_redis_connectivity(settings: Settings) -> PreflightCheck:
    """Verify Redis responds before the app begins serving traffic."""
    try:
        import redis.asyncio as aioredis
    except ImportError:
        return PreflightCheck(
            name="redis_connectivity",
            status="warn",
            required=False,
            message="Redis client package is not installed",
        )

    redis_url = settings.redis_url.get_secret_value()
    if not isinstance(redis_url, str) or not redis_url:
        return PreflightCheck(
            name="redis_connectivity",
            status="warn",
            required=False,
            message="Redis URL is unavailable for connectivity validation",
        )

    client = aioredis.from_url(
        redis_url,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    try:
        pong = await client.ping()
    except Exception as exc:
        logger.warning("preflight_redis_failed", error_class=type(exc).__name__)
        return PreflightCheck(
            name="redis_connectivity",
            status="warn" if settings.app_env == "test" else "fail",
            message="Redis connectivity check failed",
            details={"error": str(exc)},
        )
    finally:
        await client.aclose()

    return PreflightCheck(
        name="redis_connectivity",
        status="ok" if pong else "fail",
        message="Redis connectivity verified" if pong else "Redis ping returned false",
    )


async def run_startup_preflight(
    *,
    settings: Settings | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    include_runtime_checks: bool | None = None,
) -> PreflightReport:
    """Run startup preflight checks and optionally fail fast."""
    settings = settings or get_settings()
    include_runtime_checks = (
        settings.app_env != "test" if include_runtime_checks is None else include_runtime_checks
    )

    checks = [
        _check_provider_configuration(settings),
        _check_prompt_hashes(settings),
        _check_evaluation_assets(),
        _check_assistant_native_replays(settings),
        _check_export_directory(settings),
        _check_runtime_policies(settings),
        await _check_optional_integrations(settings),
    ]

    if include_runtime_checks:
        checks.append(await _check_database_extensions(session_factory))
        checks.append(await _check_redis_connectivity(settings))
    else:
        checks.append(
            PreflightCheck(
                name="runtime_connectivity",
                status="skipped",
                required=False,
                message="Runtime connectivity checks skipped in test mode",
            )
        )

    report = PreflightReport(
        status=summarize_preflight_status(checks),
        generated_at=datetime.now(UTC),
        checks=checks,
    )

    logger.info(
        "startup_preflight_completed",
        status=report.status,
        checks=[check.model_dump() for check in checks],
    )

    fail_fast = settings.startup_preflight_fail_fast is True or settings.app_env == "production"
    if fail_fast and report.status == "fail":
        msg = "Startup preflight failed; refusing to serve traffic"
        raise RuntimeError(msg)

    return report

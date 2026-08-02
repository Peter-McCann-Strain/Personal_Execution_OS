"""Small conversion and result-normalization helpers for monitoring routes."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from src.app.core.async_utils import maybe_await
from src.app.persistence.models import AgentAction

from .monitoring_models import AgentActionDTO, PolicyDecisionDTO, ToolReceiptDTO


def _action_to_dto(a: AgentAction) -> AgentActionDTO:
    return AgentActionDTO(
        id=str(a.id),
        agent_name=a.agent_name,
        action_type=a.action_type,
        model_used=a.model_used,
        tokens_in=a.tokens_in,
        tokens_out=a.tokens_out,
        cost_usd=a.cost_usd,
        duration_ms=a.duration_ms,
        input_summary=a.input_summary,
        output_summary=a.output_summary,
        trace_id=a.trace_id,
        created_at=a.created_at.isoformat(),
    )


def _tool_receipt_to_dto(record) -> ToolReceiptDTO:
    return ToolReceiptDTO(
        id=str(record.id),
        workflow_id=_optional_string_field(getattr(record, "workflow_id", None)),
        trace_id=_optional_string_field(getattr(record, "trace_id", None)),
        interaction_id=_optional_string_field(getattr(record, "interaction_id", None)),
        idempotency_key=record.idempotency_key,
        tool_name=record.tool_name,
        server_name=record.server_name,
        mutation_class=record.mutation_class,
        status=record.status,
        argument_hash=record.argument_hash,
        arguments=_optional_dict_field(getattr(record, "arguments", None)),
        audit_metadata=_optional_dict_field(getattr(record, "audit_metadata", None)),
        result_summary=record.result_summary,
        error_message=record.error_message,
        created_at=record.created_at.isoformat(),
    )


def _policy_decision_to_dto(record) -> PolicyDecisionDTO:
    return PolicyDecisionDTO(
        id=str(record.id),
        workflow_id=_optional_string_field(getattr(record, "workflow_id", None)),
        trace_id=_optional_string_field(getattr(record, "trace_id", None)),
        specialist=_optional_string_field(getattr(record, "specialist", None)),
        policy_name=record.policy_name,
        decision=record.decision,
        reason=record.reason,
        subject_type=record.subject_type,
        subject_id=_optional_string_field(getattr(record, "subject_id", None)),
        metadata=_optional_dict_field(getattr(record, "metadata_", None)),
        created_at=record.created_at.isoformat(),
    )


def _period_to_cutoff(period: str) -> datetime:
    """Convert a period string to a UTC cutoff datetime."""
    now = datetime.now(UTC)
    if period == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "7d":
        return now - timedelta(days=7)
    if period == "30d":
        return now - timedelta(days=30)
    return now - timedelta(days=7)


def _optional_string_field(value: object) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else None


def _optional_dict_field(value: object) -> dict | None:
    return value if isinstance(value, dict) else None


def _optional_bool_field(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _optional_float_field(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _optional_int_field(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return int(value)
    return None


async def _result_scalar_values(result: object) -> list[object]:
    scalars_method = getattr(result, "scalars", None)
    if not callable(scalars_method):
        return []
    scalars = await maybe_await(scalars_method())
    all_method = getattr(scalars, "all", None)
    if not callable(all_method):
        return []
    values = await maybe_await(all_method())
    if not isinstance(values, Iterable):
        return []
    return list(values)


async def _result_rows(result: object) -> list[object]:
    all_method = getattr(result, "all", None)
    if not callable(all_method):
        return []
    values = await maybe_await(all_method())
    if not isinstance(values, Iterable):
        return []
    return list(values)

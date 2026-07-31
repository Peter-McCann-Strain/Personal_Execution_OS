"""Tool contract helpers for validation, planning, and execution policy."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

import jsonschema
import structlog

from src.app.domain.constants import ToolMutationClass, ToolParallelism
from src.app.domain.models import ToolInvocationPlan, ToolSpec
from src.app.domain.runtime import AgentRuntimeConfig

logger = structlog.get_logger()


def hash_tool_arguments(arguments: dict[str, Any]) -> str:
    """Return a deterministic hash for one tool argument payload."""
    payload = json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_tool_specs(
    tools: list[dict[str, Any]],
    *,
    tool_metadata: dict[str, dict[str, Any]] | None = None,
) -> dict[str, ToolSpec]:
    """Build canonical tool specs from MCP discovery output and local policy metadata."""
    specs: dict[str, ToolSpec] = {}
    metadata_by_name = tool_metadata or {}

    for tool in tools:
        full_name = f"{tool['server_name']}__{tool['tool_name']}"
        metadata = dict(metadata_by_name.get(full_name, {}))
        mutation_class = str(metadata.get("mutation_class") or _infer_mutation_class(full_name))
        allowed_parallelism = str(
            metadata.get("allowed_parallelism")
            or (
                ToolParallelism.PARALLEL_READ_ONLY
                if mutation_class == ToolMutationClass.READ_ONLY
                else ToolParallelism.SEQUENTIAL
            )
        )
        specs[full_name] = ToolSpec(
            tool_id=full_name,
            server_name=str(tool["server_name"]),
            tool_name=str(tool["tool_name"]),
            description=str(tool.get("description", "")),
            input_schema=(
                tool.get("input_schema") or tool.get("inputSchema") or {"type": "object"}
            ),
            auth_required=bool(tool.get("auth_required", False)),
            roots=[str(root) for root in tool.get("roots", [])],
            mutation_class=mutation_class,
            allowed_parallelism=allowed_parallelism,
            metadata=metadata,
        )

    return specs


def validate_tool_arguments(
    tool_spec: ToolSpec,
    arguments: dict[str, Any],
) -> list[str]:
    """Validate tool arguments against schema and deterministic runtime rules."""
    errors: list[str] = []
    schema = tool_spec.input_schema or {"type": "object"}

    try:
        jsonschema.validate(arguments, schema)
    except jsonschema.ValidationError as exc:
        path = ".".join(str(item) for item in exc.absolute_path)
        prefix = f"{path}: " if path else ""
        errors.append(f"{prefix}{exc.message}")
    except jsonschema.SchemaError:
        logger.warning("tool_schema_invalid", tool_id=tool_spec.tool_id, exc_info=True)
        errors.append("Tool schema is invalid and cannot be trusted for execution.")

    errors.extend(_business_rule_errors(tool_spec, arguments))
    return errors


def build_invocation_plan(
    *,
    tool_block: dict[str, Any],
    tool_spec: ToolSpec,
    runtime: AgentRuntimeConfig,
    trust_label: str,
    workflow_id: str | None,
) -> ToolInvocationPlan:
    """Build the canonical tool invocation plan from a validated tool block."""
    arguments = dict(tool_block.get("input", {}))
    requires_confirmation = (
        tool_spec.mutation_class == ToolMutationClass.MUTATING
        and runtime.confirmation_policy != "never"
    )
    return ToolInvocationPlan(
        tool_id=tool_spec.tool_id,
        server_name=tool_spec.server_name,
        tool_name=tool_spec.tool_name,
        public_name=str(tool_block["name"]),
        arguments=arguments,
        input_schema=tool_spec.input_schema,
        argument_hash=hash_tool_arguments(arguments),
        idempotency_key=str(tool_block["idempotency_key"]),
        trust_context=trust_label,
        requires_confirmation=requires_confirmation,
        mutation_class=tool_spec.mutation_class,
        allowed_parallelism=tool_spec.allowed_parallelism,
        audit_metadata=dict(tool_block.get("audit", {})),
        workflow_id=workflow_id,
    )


def can_execute_in_parallel(plans: list[ToolInvocationPlan]) -> bool:
    """Return True when every planned tool call is explicitly read-only."""
    return bool(plans) and all(
        plan.mutation_class == ToolMutationClass.READ_ONLY
        and plan.allowed_parallelism == ToolParallelism.PARALLEL_READ_ONLY
        for plan in plans
    )


def _infer_mutation_class(full_name: str) -> ToolMutationClass:
    action_name = full_name.split("__", 1)[-1]
    read_only_prefixes = (
        "get_",
        "list_",
        "read_",
        "search_",
        "find_",
        "fetch_",
    )
    if action_name.startswith(read_only_prefixes):
        return ToolMutationClass.READ_ONLY
    return ToolMutationClass.MUTATING


def _business_rule_errors(tool_spec: ToolSpec, arguments: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    for key in ("path", "file_path"):
        value = arguments.get(key)
        if isinstance(value, str) and tool_spec.roots:
            path = PurePosixPath(value)
            if value.startswith("/") or ".." in path.parts:
                errors.append(f"{key}: path must stay relative to the configured roots")
    for key in ("paths", "file_paths"):
        value = arguments.get(key)
        if isinstance(value, list) and tool_spec.roots:
            for index, entry in enumerate(value):
                if not isinstance(entry, str):
                    continue
                path = PurePosixPath(entry)
                if entry.startswith("/") or ".." in path.parts:
                    errors.append(
                        f"{key}[{index}]: path must stay relative to the configured roots"
                    )

    for key in ("limit", "max_results", "max_items"):
        value = arguments.get(key)
        if isinstance(value, int) and value > 100:
            errors.append(f"{key}: value must be 100 or less")

    for key, max_value in (("max_chars", 10_000), ("output_size", 10_000), ("max_tokens", 8_000)):
        value = arguments.get(key)
        if isinstance(value, int) and value > max_value:
            errors.append(f"{key}: value must be {max_value} or less")

    if tool_spec.server_name == "google-gmail":
        for recipient_key in ("to", "cc", "bcc"):
            recipient = arguments.get(recipient_key)
            if isinstance(recipient, str) and ("\n" in recipient or "\r" in recipient):
                errors.append(
                    f"{recipient_key}: recipient must be a single-line address or list entry"
                )
            if isinstance(recipient, list) and len(recipient) > 50:
                errors.append(f"{recipient_key}: maximum recipient list size is 50")

    for start_key, end_key in (
        ("start_date", "end_date"),
        ("date_from", "date_to"),
        ("start", "end"),
        ("from_date", "to_date"),
    ):
        start_value = _coerce_datetime(arguments.get(start_key))
        end_value = _coerce_datetime(arguments.get(end_key))
        if start_value is None or end_value is None:
            continue
        if end_value < start_value:
            errors.append(f"{end_key}: must be on or after {start_key}")
            continue
        if (end_value - start_value).days > 366:
            errors.append(f"{end_key}: date window must be 366 days or less from {start_key}")

    return errors


def _coerce_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None

    candidate = value.strip()
    if not candidate:
        return None
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"

    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None

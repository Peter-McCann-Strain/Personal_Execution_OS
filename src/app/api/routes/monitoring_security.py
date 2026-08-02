"""Runtime policy and mutation-safety security metrics."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.deps import get_db

from .monitoring_models import SecurityMetricsDTO

router = APIRouter()


@router.get("/ops/security-metrics", response_model=SecurityMetricsDTO)
async def security_metrics(
    session: AsyncSession = Depends(get_db),
    decision_limit: int = Query(500, ge=1, le=5000),
    receipt_limit: int = Query(500, ge=1, le=5000),
) -> SecurityMetricsDTO:
    """Aggregate runtime policy and mutation-safety security metrics."""
    from src.app.api.routes import monitoring as monitoring_facade

    policies = list(await monitoring_facade.list_policy_decisions(session, limit=decision_limit))
    receipts = list(await monitoring_facade.list_tool_receipts(session, limit=receipt_limit))

    policy_counts: dict[str, int] = {}
    decision_counts: dict[str, int] = {}
    for record in policies:
        policy_name = str(getattr(record, "policy_name", "") or "unknown")
        policy_counts[policy_name] = policy_counts.get(policy_name, 0) + 1
        decision = str(getattr(record, "decision", "") or "unknown")
        decision_counts[decision] = decision_counts.get(decision, 0) + 1

    instruction_risk_decisions = sum(
        1
        for record in policies
        if str(getattr(record, "policy_name", "")) == "instruction_like_content"
    )
    trust_boundary_denies = sum(
        1
        for record in policies
        if str(getattr(record, "policy_name", "")) == "tool_trust_boundary"
        and str(getattr(record, "decision", "")) == "deny"
    )
    confirmation_required_count = sum(
        1
        for record in policies
        if str(getattr(record, "policy_name", "")) == "tool_confirmation"
        and str(getattr(record, "decision", "")) == "require_confirmation"
    )
    confirmation_allowed_count = sum(
        1
        for record in policies
        if str(getattr(record, "policy_name", "")) == "tool_confirmation"
        and str(getattr(record, "decision", "")) == "allow"
    )
    confirmation_denied_count = sum(
        1
        for record in policies
        if str(getattr(record, "policy_name", "")) == "tool_confirmation"
        and str(getattr(record, "decision", "")) == "deny"
    )

    mutating_receipts = [
        record for record in receipts if str(getattr(record, "mutation_class", "")) == "mutating"
    ]
    mutating_without_confirmation_count = 0
    failed_mutating_receipt_count = 0
    suspicious_tool_receipt_count = 0
    idempotency_counts: dict[str, int] = {}
    for record in mutating_receipts:
        audit = getattr(record, "audit_metadata", None)
        audit_metadata = audit if isinstance(audit, dict) else {}
        if not bool(audit_metadata.get("confirmation_required", False)):
            mutating_without_confirmation_count += 1
        if str(getattr(record, "status", "")) == "failed":
            failed_mutating_receipt_count += 1
        if bool(audit_metadata.get("instruction_like_content", False)):
            suspicious_tool_receipt_count += 1

    for record in receipts:
        key = str(getattr(record, "idempotency_key", "") or "")
        if key:
            idempotency_counts[key] = idempotency_counts.get(key, 0) + 1
    duplicate_idempotency_key_count = sum(
        count - 1 for count in idempotency_counts.values() if count > 1
    )

    confirmation_coverage: float | None = None
    if confirmation_required_count:
        confirmation_coverage = round(
            min(
                1.0,
                (confirmation_allowed_count + confirmation_denied_count)
                / confirmation_required_count,
            ),
            3,
        )

    return SecurityMetricsDTO(
        generated_at=datetime.now(UTC).isoformat(),
        policy_decision_count=len(policies),
        tool_receipt_count=len(receipts),
        instruction_risk_decisions=instruction_risk_decisions,
        trust_boundary_denies=trust_boundary_denies,
        confirmation_required_count=confirmation_required_count,
        confirmation_allowed_count=confirmation_allowed_count,
        confirmation_denied_count=confirmation_denied_count,
        confirmation_coverage=confirmation_coverage,
        mutating_receipt_count=len(mutating_receipts),
        mutating_without_confirmation_count=mutating_without_confirmation_count,
        failed_mutating_receipt_count=failed_mutating_receipt_count,
        suspicious_tool_receipt_count=suspicious_tool_receipt_count,
        duplicate_idempotency_key_count=duplicate_idempotency_key_count,
        policy_counts=policy_counts,
        decision_counts=decision_counts,
    )

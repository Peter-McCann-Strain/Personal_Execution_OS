"""Explicitly scoped core-data export helpers."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.persistence.models import (
    Commitment,
    Contact,
    Decision,
    Episode,
    Goal,
    Habit,
    Interaction,
    Note,
    Project,
    Review,
    SavedMemory,
    Task,
)

EXPORT_MODELS = (
    ("episodes", Episode),
    ("goals", Goal),
    ("notes", Note),
    ("projects", Project),
    ("tasks", Task),
    ("contacts", Contact),
    ("interactions", Interaction),
    ("reviews", Review),
    ("habits", Habit),
    ("decisions", Decision),
    ("commitments", Commitment),
    ("saved_memories", SavedMemory),
)


def _serialize_value(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _serialize_value(item) for key, item in value.items()}
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _serialize_model(row: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for column in row.__table__.columns:
        attribute_key = row.__mapper__.get_property_by_column(column).key
        payload[column.name] = _serialize_value(getattr(row, attribute_key))
    return payload


async def build_core_data_export_payload(
    session: AsyncSession,
    *,
    account_id: uuid.UUID,
) -> dict[str, Any]:
    """Build a JSON payload for the enumerated core application tables.

    This is intentionally not presented as a complete privacy or portability
    export: connector-provider data, files, logs, caches, backups, and external
    model-provider records are outside its scope.
    """
    tables: dict[str, list[dict[str, Any]]] = {}
    for table_name, model in EXPORT_MODELS:
        stmt = select(model).where(model.account_id == account_id)
        created_at = getattr(model, "created_at", None)
        if created_at is not None:
            stmt = stmt.order_by(created_at.asc())
        result = await session.execute(stmt)
        tables[table_name] = [_serialize_model(row) for row in result.scalars()]

    return {
        "account_id": str(account_id),
        "generated_at": datetime.now(UTC).isoformat(),
        "format": "personal-execution-os.core-data-export.v1",
        "scope": "core_database_records",
        "included_tables": [table_name for table_name, _model in EXPORT_MODELS],
        "excluded_categories": [
            "connector_provider_data",
            "uploaded_files",
            "logs_and_caches",
            "backups",
            "external_model_provider_records",
        ],
        "tables": tables,
    }


__all__ = ["build_core_data_export_payload"]

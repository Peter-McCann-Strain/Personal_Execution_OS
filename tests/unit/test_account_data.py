"""Focused tests for explicitly scoped account-data exports."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from src.app.domain.services import account_data
from src.app.persistence.models import Episode

ACCOUNT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
EPISODE_ID = uuid.UUID("00000000-0000-0000-0000-000000000101")
NOW = datetime(2026, 5, 18, 12, 30, tzinfo=UTC)


class _TestBase(DeclarativeBase):
    pass


class _UndatedExportRow(_TestBase):
    """Mapped test row covering the export path without a created_at column."""

    __tablename__ = "test_undated_export_rows"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    account_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)


class _PrintableValue:
    def __str__(self) -> str:
        return "printable-value"


def _result(rows: list[object]) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value = rows
    return result


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (EPISODE_ID, str(EPISODE_ID)),
        (NOW, NOW.isoformat()),
        (date(2026, 5, 18), "2026-05-18"),
        (Decimal("12.375"), 12.375),
        (None, None),
        ("text", "text"),
        (7, 7),
        (2.5, 2.5),
        (True, True),
        (_PrintableValue(), "printable-value"),
    ],
)
def test_serialize_value_handles_supported_scalars_and_safe_fallback(
    value: object,
    expected: object,
) -> None:
    assert account_data._serialize_value(value) == expected


def test_serialize_value_recurses_through_lists_and_stringifies_mapping_keys() -> None:
    value = {
        EPISODE_ID: [
            Decimal("1.5"),
            {
                "created": NOW,
                "nested_id": EPISODE_ID,
            },
        ]
    }

    assert account_data._serialize_value(value) == {
        str(EPISODE_ID): [
            1.5,
            {
                "created": NOW.isoformat(),
                "nested_id": str(EPISODE_ID),
            },
        ]
    }


def test_serialize_model_uses_mapper_attribute_for_renamed_database_columns() -> None:
    episode = Episode(
        id=EPISODE_ID,
        account_id=ACCOUNT_ID,
        content="A private journal entry",
        summary="Journal summary",
        metadata_={
            "confidence": Decimal("0.75"),
            "source_ids": [EPISODE_ID],
        },
        tags=["private", "reflection"],
        created_at=NOW,
    )

    payload = account_data._serialize_model(episode)

    assert payload["id"] == str(EPISODE_ID)
    assert payload["account_id"] == str(ACCOUNT_ID)
    assert payload["created_at"] == NOW.isoformat()
    assert payload["metadata"] == {
        "confidence": 0.75,
        "source_ids": [str(EPISODE_ID)],
    }
    assert "metadata_" not in payload
    assert payload["content"] == "A private journal entry"


async def test_build_core_data_export_payload_returns_all_tables_and_serialized_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            assert tz is UTC
            return NOW

    monkeypatch.setattr(account_data, "datetime", _FrozenDateTime)
    episode = Episode(
        id=EPISODE_ID,
        account_id=ACCOUNT_ID,
        content="Export me",
        metadata_={"nested": [Decimal("2.25")]},
        created_at=NOW,
    )
    results = [_result([episode])]
    results.extend(_result([]) for _ in account_data.EXPORT_MODELS[1:])
    session = MagicMock()
    session.execute = AsyncMock(side_effect=results)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    payload = await account_data.build_core_data_export_payload(
        session,
        account_id=ACCOUNT_ID,
    )

    expected_tables = [table_name for table_name, _model in account_data.EXPORT_MODELS]
    assert payload == {
        "account_id": str(ACCOUNT_ID),
        "generated_at": NOW.isoformat(),
        "format": "personal-execution-os.core-data-export.v1",
        "scope": "core_database_records",
        "included_tables": expected_tables,
        "excluded_categories": [
            "connector_provider_data",
            "uploaded_files",
            "logs_and_caches",
            "backups",
            "external_model_provider_records",
        ],
        "tables": {
            **{table_name: [] for table_name in expected_tables},
            "episodes": [account_data._serialize_model(episode)],
        },
    }
    assert session.execute.await_count == len(account_data.EXPORT_MODELS)
    for call in session.execute.await_args_list:
        statement = call.args[0]
        rendered_statement = str(statement)
        assert "account_id" in rendered_statement
        assert "ORDER BY" in rendered_statement
        assert " ASC" in rendered_statement
    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()


async def test_build_core_data_export_payload_handles_an_empty_account() -> None:
    session = MagicMock()
    session.execute = AsyncMock(return_value=_result([]))
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    payload = await account_data.build_core_data_export_payload(
        session,
        account_id=ACCOUNT_ID,
    )

    assert payload["account_id"] == str(ACCOUNT_ID)
    assert payload["included_tables"] == [
        table_name for table_name, _model in account_data.EXPORT_MODELS
    ]
    assert all(rows == [] for rows in payload["tables"].values())
    assert session.execute.await_count == len(account_data.EXPORT_MODELS)
    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()


async def test_build_core_data_export_payload_supports_models_without_created_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        account_data,
        "EXPORT_MODELS",
        (("undated_records", _UndatedExportRow),),
    )
    row = _UndatedExportRow(
        id=EPISODE_ID,
        account_id=ACCOUNT_ID,
        label="Legacy row",
    )
    session = MagicMock()
    session.execute = AsyncMock(return_value=_result([row]))

    payload = await account_data.build_core_data_export_payload(
        session,
        account_id=ACCOUNT_ID,
    )

    assert payload["included_tables"] == ["undated_records"]
    assert payload["tables"] == {
        "undated_records": [
            {
                "id": str(EPISODE_ID),
                "account_id": str(ACCOUNT_ID),
                "label": "Legacy row",
            }
        ]
    }
    statement = session.execute.await_args.args[0]
    assert "ORDER BY" not in str(statement)


async def test_build_core_data_export_payload_propagates_query_failure_without_transactions() -> (
    None
):
    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=[
            _result([]),
            RuntimeError("database export failed"),
        ]
    )
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    with pytest.raises(RuntimeError, match="database export failed"):
        await account_data.build_core_data_export_payload(
            session,
            account_id=ACCOUNT_ID,
        )

    assert session.execute.await_count == 2
    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()

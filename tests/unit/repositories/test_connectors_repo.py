"""Type-boundary regression tests for connector document persistence."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.persistence.repositories.connectors import list_connector_documents


async def test_list_connector_documents_accepts_sqlalchemy_shaped_results() -> None:
    session = AsyncMock()
    first = MagicMock()
    second = MagicMock()
    count_result = MagicMock()
    count_result.scalar_one.return_value = 2
    rows_result = MagicMock()
    rows_result.scalars.return_value.all.return_value = [first, second]
    session.execute.side_effect = [count_result, rows_result]

    rows, total = await list_connector_documents(
        session,
        user_id="owner",
        search=" report ",
        source_type="drive",
        limit=2,
        offset=3,
    )

    assert rows == [first, second]
    assert total == 2
    assert session.execute.await_count == 2
    count_sql = str(session.execute.await_args_list[0].args[0])
    assert "connector_accounts.user_id" in count_sql
    assert "connector_documents.source_type" in count_sql
    assert "lower(connector_documents.title)" in count_sql


async def test_list_connector_documents_rejects_malformed_count_rows() -> None:
    session = AsyncMock()
    count_result = MagicMock()
    count_result.scalar_one.return_value = "1"
    session.execute.return_value = count_result

    with pytest.raises(TypeError, match="count query returned a non-integer"):
        await list_connector_documents(session, user_id="owner")

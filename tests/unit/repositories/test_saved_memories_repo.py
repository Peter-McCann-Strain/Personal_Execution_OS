"""Owner-scoping, merge semantics, and transaction tests for saved memories."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.persistence.models import SavedMemory
from src.app.persistence.repositories.saved_memories import (
    _merge_memory_content,
    create_saved_memory,
    get_saved_memory,
    list_saved_memories,
    mark_saved_memories_used,
    merge_saved_memories,
    search_saved_memories,
    soft_delete_saved_memory,
    update_saved_memory,
)


class _Scalars:
    def __init__(self, rows: list[object] | None = None) -> None:
        self._rows = list(rows or [])

    def all(self) -> list[object]:
        return list(self._rows)


class _Result:
    def __init__(
        self,
        *,
        one_or_none: object | None = None,
        one: object | None = None,
        rows: list[object] | None = None,
    ) -> None:
        self._one_or_none = one_or_none
        self._one = one
        self._rows = list(rows or [])

    def scalar_one_or_none(self) -> object | None:
        return self._one_or_none

    def scalar_one(self) -> object | None:
        return self._one

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)


class _AsyncScalars:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    async def all(self) -> list[object]:
        return list(self._rows)


class _AsyncRowsResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    async def scalars(self) -> _AsyncScalars:
        return _AsyncScalars(self._rows)


class _AsyncCountResult:
    def __init__(self, value: int) -> None:
        self._value = value

    async def _resolved(self) -> int:
        return self._value

    def scalar_one(self):
        return self._resolved()


def _session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.execute = AsyncMock(return_value=_Result(rows=[]))
    return session


def _memory(**overrides: object) -> SavedMemory:
    memory = SavedMemory()
    memory.id = overrides.get("id", uuid.uuid4())
    memory.user_id = overrides.get("user_id", "owner")
    memory.title = overrides.get("title", "Writing preference")
    memory.content = overrides.get("content", "Lead with evidence.")
    memory.scope = overrides.get("scope", "global")
    memory.scope_key = overrides.get("scope_key")
    memory.state = overrides.get("state", "active")
    memory.source_type = overrides.get("source_type")
    memory.source_id = overrides.get("source_id")
    memory.provenance = overrides.get("provenance", {})
    memory.pinned = overrides.get("pinned", False)
    memory.auto_captured = overrides.get("auto_captured", False)
    memory.last_used_at = overrides.get("last_used_at")
    memory.last_confirmed_at = overrides.get("last_confirmed_at")
    memory.deleted_at = overrides.get("deleted_at")
    memory.created_at = overrides.get("created_at", datetime(2026, 8, 1, tzinfo=UTC))
    memory.updated_at = overrides.get("updated_at", datetime(2026, 8, 1, tzinfo=UTC))
    return memory


@pytest.mark.asyncio
async def test_create_covers_defaults_custom_values_and_add_variants() -> None:
    session = _session()
    created = await create_saved_memory(
        session,
        user_id="owner",
        title="Preference",
        content="Be concise",
    )
    assert created.scope == "global"
    assert created.provenance == {}
    assert created.pinned is False
    assert created.auto_captured is False
    session.add.assert_called_once_with(created)
    session.flush.assert_awaited_once()
    session.commit.assert_not_awaited()

    async_add_session = _session()
    async_add_session.add = AsyncMock()
    custom = await create_saved_memory(
        async_add_session,
        user_id="owner",
        title="Project context",
        content="Ship in August",
        scope="project",
        scope_key="project-1",
        source_type="note",
        source_id="note-1",
        provenance={"source": "manual"},
        pinned=True,
        auto_captured=True,
    )
    assert custom.scope == "project"
    assert custom.scope_key == "project-1"
    assert custom.source_type == "note"
    assert custom.source_id == "note-1"
    assert custom.provenance == {"source": "manual"}
    assert custom.pinned is True
    assert custom.auto_captured is True
    async_add_session.add.assert_awaited_once_with(custom)


@pytest.mark.asyncio
async def test_get_and_list_are_owner_scoped_with_empty_and_filter_paths() -> None:
    session = _session()
    memory = _memory()
    session.execute.side_effect = [
        _Result(one_or_none=memory),
        _Result(one_or_none=None),
        _Result(one=1),
        _Result(rows=[memory]),
        _Result(one=0),
        _Result(rows=[]),
    ]

    assert (
        await get_saved_memory(
            session,
            memory_id=memory.id,
            user_id="owner",
        )
        is memory
    )
    assert (
        await get_saved_memory(
            session,
            memory_id=memory.id,
            user_id="other",
        )
        is None
    )
    rows, total = await list_saved_memories(
        session,
        user_id="owner",
        search=" evidence ",
        scope="global",
        state="active",
        limit=7,
        offset=2,
    )
    assert rows == [memory]
    assert total == 1
    empty, empty_total = await list_saved_memories(session, user_id="other")
    assert empty == []
    assert empty_total == 0

    get_sql = str(session.execute.await_args_list[0].args[0])
    count_sql = str(session.execute.await_args_list[2].args[0])
    assert "saved_memories.user_id" in get_sql
    assert "saved_memories.deleted_at IS NULL" in get_sql
    assert "saved_memories.user_id" in count_sql
    assert "lower(saved_memories.title)" in count_sql
    assert "saved_memories.scope" in count_sql
    assert "saved_memories.state" in count_sql


@pytest.mark.asyncio
async def test_list_supports_async_result_adapters() -> None:
    session = _session()
    memory = _memory()
    session.execute.side_effect = [
        _AsyncCountResult(1),
        _AsyncRowsResult([memory]),
    ]

    rows, total = await list_saved_memories(session, user_id="owner")

    assert rows == [memory]
    assert total == 1


@pytest.mark.asyncio
async def test_list_rejects_malformed_count_rows() -> None:
    session = _session()
    session.execute.return_value = _Result(one="1")

    with pytest.raises(TypeError, match="count query returned a non-integer"):
        await list_saved_memories(session, user_id="owner")


@pytest.mark.asyncio
async def test_update_respects_owner_and_covers_all_optional_fields() -> None:
    session = _session()
    memory = _memory()
    with patch(
        "src.app.persistence.repositories.saved_memories.get_saved_memory",
        new=AsyncMock(side_effect=[None, memory, memory]),
    ):
        assert (
            await update_saved_memory(
                session,
                memory_id=memory.id,
                user_id="other",
                title="Forbidden",
            )
            is None
        )
        updated = await update_saved_memory(
            session,
            memory_id=memory.id,
            user_id="owner",
            title="Updated",
            content="Updated content",
            scope="project",
            scope_key="project-1",
            state="snoozed",
            provenance={"reviewed": True},
            pinned=True,
            auto_captured=True,
            last_used=True,
            confirm_now=True,
        )
        assert updated is memory
        assert memory.title == "Updated"
        assert memory.content == "Updated content"
        assert memory.scope == "project"
        assert memory.scope_key == "project-1"
        assert memory.state == "snoozed"
        assert memory.provenance == {"reviewed": True}
        assert memory.pinned is True
        assert memory.auto_captured is True
        assert memory.last_used_at is not None
        assert memory.last_confirmed_at is not None

        assert (
            await update_saved_memory(
                session,
                memory_id=memory.id,
                user_id="owner",
            )
            is memory
        )

    assert session.flush.await_count == 2
    session.commit.assert_not_awaited()


def test_merge_content_removes_blank_and_normalized_duplicates() -> None:
    assert (
        _merge_memory_content(
            [" First fact ", "first   FACT", "", "Second fact"],
        )
        == "First fact\n\n---\n\nSecond fact"
    )


@pytest.mark.asyncio
async def test_merge_handles_missing_target_noop_and_missing_owner_sources() -> None:
    session = _session()
    target = _memory()
    source_id = uuid.uuid4()
    with patch(
        "src.app.persistence.repositories.saved_memories.get_saved_memory",
        new=AsyncMock(side_effect=[None, target, target]),
    ):
        assert (
            await merge_saved_memories(
                session,
                target_memory_id=target.id,
                source_memory_ids=[source_id],
                user_id="owner",
            )
            is None
        )
        assert (
            await merge_saved_memories(
                session,
                target_memory_id=target.id,
                source_memory_ids=[target.id, target.id],
                user_id="owner",
            )
            is target
        )

        session.execute.return_value = _Result(rows=[])
        assert (
            await merge_saved_memories(
                session,
                target_memory_id=target.id,
                source_memory_ids=[source_id, source_id],
                user_id="owner",
            )
            is None
        )

    assert "saved_memories.user_id" in str(session.execute.await_args.args[0])
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("states", "expected_state"),
    [
        (("archived", "active"), "active"),
        (("archived", "snoozed"), "snoozed"),
        (("archived", "archived"), "archived"),
    ],
)
async def test_merge_combines_state_provenance_timestamps_and_soft_deletes_sources(
    states: tuple[str, str],
    expected_state: str,
) -> None:
    session = _session()
    older = datetime(2026, 7, 1, tzinfo=UTC)
    newer = older + timedelta(days=1)
    target = _memory(
        title="Target",
        content="First fact",
        state=states[0],
        provenance={"kept": True},
        auto_captured=True,
        last_used_at=None,
        last_confirmed_at=older,
    )
    source = _memory(
        title="Source",
        content="Second fact",
        state=states[1],
        pinned=expected_state == "active",
        auto_captured=expected_state != "archived",
        last_used_at=newer,
        last_confirmed_at=newer,
    )
    session.execute.return_value = _Result(rows=[source])

    with patch(
        "src.app.persistence.repositories.saved_memories.get_saved_memory",
        new=AsyncMock(return_value=target),
    ):
        merged = await merge_saved_memories(
            session,
            target_memory_id=target.id,
            source_memory_ids=[source.id, source.id, target.id],
            user_id="owner",
        )

    assert merged is target
    assert merged.state == expected_state
    assert merged.content == "First fact\n\n---\n\nSecond fact"
    assert merged.last_used_at == newer
    assert merged.last_confirmed_at == newer
    assert merged.provenance["kept"] is True
    assert merged.provenance["merged_from_ids"] == [str(source.id)]
    assert merged.provenance["merged_from_titles"] == ["Source"]
    assert merged.provenance["merged_count"] == 1
    assert source.deleted_at is not None
    assert source.updated_at == target.updated_at
    session.flush.assert_awaited_once()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_soft_delete_covers_missing_owner_and_success() -> None:
    session = _session()
    memory = _memory()
    with patch(
        "src.app.persistence.repositories.saved_memories.get_saved_memory",
        new=AsyncMock(side_effect=[None, memory]),
    ):
        assert (
            await soft_delete_saved_memory(
                session,
                memory_id=memory.id,
                user_id="other",
            )
            is False
        )
        assert (
            await soft_delete_saved_memory(
                session,
                memory_id=memory.id,
                user_id="owner",
            )
            is True
        )
    assert memory.deleted_at is not None
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_used_covers_empty_missing_deduplication_and_owner_scope() -> None:
    session = _session()
    first = _memory()
    second = _memory()

    assert (
        await mark_saved_memories_used(
            session,
            user_id="owner",
            memory_ids=[],
        )
        == 0
    )
    session.execute.side_effect = [
        _Result(rows=[]),
        _Result(rows=[first, second]),
    ]
    assert (
        await mark_saved_memories_used(
            session,
            user_id="owner",
            memory_ids=[first.id],
        )
        == 0
    )
    assert (
        await mark_saved_memories_used(
            session,
            user_id="owner",
            memory_ids=[first.id, first.id, second.id],
        )
        == 2
    )
    assert first.last_used_at == second.last_used_at
    assert first.updated_at == second.updated_at
    assert "saved_memories.user_id" in str(session.execute.await_args_list[1].args[0])
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_search_delegates_to_active_filtered_list() -> None:
    session = _session()
    memory = _memory()
    with patch(
        "src.app.persistence.repositories.saved_memories.list_saved_memories",
        new=AsyncMock(return_value=([memory], 1)),
    ) as list_mock:
        assert await search_saved_memories(
            session,
            user_id="owner",
            query="evidence",
            limit=3,
        ) == [memory]
    list_mock.assert_awaited_once_with(
        session,
        user_id="owner",
        limit=3,
        offset=0,
        search="evidence",
        state="active",
    )


@pytest.mark.asyncio
async def test_flush_failure_propagates_without_commit() -> None:
    session = _session()
    session.flush.side_effect = RuntimeError("write failed")

    with pytest.raises(RuntimeError, match="write failed"):
        await create_saved_memory(
            session,
            user_id="owner",
            title="Failure",
            content="Failure",
        )

    session.commit.assert_not_awaited()

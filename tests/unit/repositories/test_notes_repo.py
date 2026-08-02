"""Tests for the current notes repository surface."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.persistence.models import Note, NoteLink
from src.app.persistence.repositories.notes import (
    _find_note_by_reference,
    create_note,
    create_note_link,
    delete_note,
    get_linked_notes,
    get_note_by_id,
    search_notes,
    update_note,
)


class _MockScalars:
    def __init__(self, rows: list[object] | None = None) -> None:
        self._rows = list(rows or [])

    def all(self) -> list[object]:
        return list(self._rows)


class _MockResult:
    def __init__(
        self,
        *,
        scalar_one_or_none: object | None = None,
        scalar_one: object | None = None,
        rows: list[object] | None = None,
        rowcount: int = 0,
    ) -> None:
        self._scalar_one_or_none = scalar_one_or_none
        self._scalar_one = scalar_one
        self._rows = list(rows or [])
        self.rowcount = rowcount

    def scalar_one_or_none(self) -> object | None:
        return self._scalar_one_or_none

    def scalar_one(self) -> object | None:
        return self._scalar_one

    def scalars(self) -> _MockScalars:
        return _MockScalars(self._rows)

    def all(self) -> list[object]:
        return list(self._rows)


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.get = AsyncMock()
    session.execute = AsyncMock(return_value=_MockResult(rows=[]))
    return session


def _make_note(**overrides: object) -> Note:
    note = Note()
    note.id = overrides.get("id", uuid.uuid4())
    note.title = overrides.get("title", "Atomic Habits Summary")
    note.slug = overrides.get("slug", "atomic-habits-summary")
    note.aliases = overrides.get("aliases")
    note.kind = overrides.get("kind", "note")
    note.daily_date = overrides.get("daily_date")
    note.frontmatter = overrides.get("frontmatter", {})
    note.content = overrides.get("content", "Small habits compound over time.")
    note.note_type = overrides.get("note_type", "fleeting")
    note.para_category = overrides.get("para_category")
    note.progressive_summary_level = overrides.get("progressive_summary_level", 1)
    note.executive_summary = overrides.get("executive_summary")
    note.source_url = overrides.get("source_url")
    note.tags = overrides.get("tags")
    note.embedding = overrides.get("embedding")
    note.deleted_at = overrides.get("deleted_at")
    note.created_at = overrides.get("created_at", datetime.now(UTC))
    note.updated_at = overrides.get("updated_at", datetime.now(UTC))
    return note


async def test_reference_lookup_uses_postgres_array_membership() -> None:
    session = _make_session()

    assert (
        await _find_note_by_reference(
            session,
            reference="Alternative title",
        )
        is None
    )

    statement = str(session.execute.await_args.args[0])
    assert "= ANY (notes.aliases)" in statement


@pytest.mark.asyncio
async def test_create_note_adds_and_flushes() -> None:
    session = _make_session()

    result = await create_note(session, title="Test Note", content="Test content")

    session.add.assert_called_once()
    session.flush.assert_awaited_once()
    assert isinstance(result, Note)
    assert result.slug == "test-note"
    assert result.kind == "note"


@pytest.mark.asyncio
async def test_create_note_sets_optional_fields() -> None:
    session = _make_session()

    result = await create_note(
        session,
        title="Deep Work Summary",
        content="Cal Newport's framework for focused work",
        note_type="literature",
        para_category="resource",
        tags=["productivity", "focus"],
        source_url="https://example.com/deep-work",
        aliases=["Focused Work"],
        kind="moc",
        frontmatter={"status": "draft"},
    )

    assert result.title == "Deep Work Summary"
    assert result.slug == "deep-work-summary"
    assert result.aliases == ["Focused Work"]
    assert result.kind == "moc"
    assert result.frontmatter == {"status": "draft"}
    assert result.note_type == "literature"
    assert result.para_category == "resource"
    assert result.tags == ["productivity", "focus"]
    assert result.source_url == "https://example.com/deep-work"


@pytest.mark.asyncio
async def test_create_note_link_creates_new_link() -> None:
    session = _make_session()
    source_id = uuid.uuid4()
    target_id = uuid.uuid4()
    session.execute.return_value = _MockResult(scalar_one_or_none=None)

    result = await create_note_link(
        session,
        source_id,
        target_id,
        link_reason="same topic",
        similarity_score=0.87,
        auto_discovered=False,
        link_type="semantic",
        origin="semantic",
    )

    session.add.assert_called_once()
    session.flush.assert_awaited_once()
    assert isinstance(result, NoteLink)
    assert result.source_note_id == source_id
    assert result.target_note_id == target_id
    assert result.link_reason == "same topic"
    assert result.similarity_score == 0.87
    assert result.auto_discovered is False
    assert result.link_type == "semantic"
    assert result.origin == "semantic"


@pytest.mark.asyncio
async def test_create_note_link_returns_existing_link() -> None:
    session = _make_session()
    link_id = uuid.uuid4()
    existing_link = NoteLink(id=link_id)
    session.execute.return_value = _MockResult(scalar_one_or_none=link_id)
    session.get.return_value = existing_link

    result = await create_note_link(session, uuid.uuid4(), uuid.uuid4())

    session.add.assert_not_called()
    session.flush.assert_not_awaited()
    session.get.assert_awaited_once_with(NoteLink, link_id)
    assert result is existing_link


@pytest.mark.asyncio
async def test_get_note_by_id_returns_note() -> None:
    session = _make_session()
    note = _make_note(title="Found note")
    session.execute.return_value = _MockResult(scalar_one_or_none=note)

    result = await get_note_by_id(session, note.id)

    session.execute.assert_awaited_once()
    assert result is note


@pytest.mark.asyncio
async def test_get_note_by_id_returns_none_when_missing() -> None:
    session = _make_session()
    session.execute.return_value = _MockResult(scalar_one_or_none=None)

    result = await get_note_by_id(session, uuid.uuid4())

    assert result is None


@pytest.mark.asyncio
async def test_update_note_regenerates_slug_and_flushes() -> None:
    session = _make_session()
    note = _make_note(title="Original", slug="original")
    session.execute.side_effect = [
        _MockResult(scalar_one_or_none=note),
        _MockResult(scalar_one_or_none=None),
        _MockResult(rowcount=0),
        _MockResult(rows=[]),
    ]

    result = await update_note(session, note.id, title="Renamed Note")

    assert result is note
    assert result.title == "Renamed Note"
    assert result.slug == "renamed-note"
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_note_raises_when_missing() -> None:
    session = _make_session()
    session.execute.return_value = _MockResult(scalar_one_or_none=None)

    with pytest.raises(ValueError, match="Note not found"):
        await update_note(session, uuid.uuid4(), title="new title")


@pytest.mark.asyncio
async def test_delete_note_returns_true_when_deleted() -> None:
    session = _make_session()
    session.execute.return_value = _MockResult(rowcount=1)

    result = await delete_note(session, uuid.uuid4())

    assert result is True


@pytest.mark.asyncio
async def test_get_linked_notes_returns_serialized_rows() -> None:
    session = _make_session()
    note = _make_note(title="Related Note", tags=["productivity"])
    link = NoteLink(
        id=uuid.uuid4(),
        source_note_id=uuid.uuid4(),
        target_note_id=uuid.uuid4(),
        link_reason="same topic",
        similarity_score=0.92,
        auto_discovered=True,
        link_type="semantic",
        origin="semantic",
    )
    session.execute.return_value = _MockResult(rows=[(link, note)])

    results = await get_linked_notes(session, uuid.uuid4())

    assert len(results) == 1
    assert results[0]["title"] == "Related Note"
    assert results[0]["slug"] == note.slug
    assert results[0]["link_reason"] == "same topic"
    assert results[0]["similarity_score"] == 0.92
    assert results[0]["link_type"] == "semantic"
    assert results[0]["origin"] == "semantic"


@pytest.mark.asyncio
async def test_search_notes_returns_serialized_rows() -> None:
    session = _make_session()
    note = _make_note(title="Habits", content="Small habits compound over time.", tags=["habits"])
    session.execute.side_effect = [
        _MockResult(scalar_one=1),
        _MockResult(rows=[note]),
    ]

    results = await search_notes(session, "habits")

    assert len(results) == 1
    assert results[0]["title"] == "Habits"
    assert results[0]["slug"] == note.slug
    assert results[0]["tags"] == ["habits"]

"""Source-lineage, empty-state, and transaction tests for content assets."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.persistence.models import ContentAsset, Note, Project, Task
from src.app.persistence.repositories.content_assets import (
    _build_source_pack,
    _default_template_prompt,
    _note_source_pack,
    _project_source_pack,
    _task_source_pack,
    create_content_asset,
    generate_content_source_pack,
    get_content_asset,
    list_content_assets,
    update_content_asset,
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


def _session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.get = AsyncMock()
    session.execute = AsyncMock(return_value=_Result(rows=[]))
    return session


def _note(**overrides: object) -> Note:
    note = Note()
    note.id = overrides.get("id", uuid.uuid4())
    note.title = overrides.get("title", "Research note")
    note.slug = overrides.get("slug", "research-note")
    note.kind = overrides.get("kind", "note")
    note.executive_summary = overrides.get("executive_summary", "Evidence summary")
    note.tags = overrides.get("tags", ["research"])
    note.content = overrides.get("content", "Primary evidence")
    note.source_url = overrides.get("source_url", "https://example.test/source")
    note.deleted_at = overrides.get("deleted_at")
    return note


def _project(**overrides: object) -> Project:
    project = Project()
    project.id = overrides.get("id", uuid.uuid4())
    project.title = overrides.get("title", "Launch")
    project.description = overrides.get("description", "Ship a reliable release")
    project.status = overrides.get("status", "active")
    project.appetite = overrides.get("appetite", "medium")
    project.deadline = overrides.get(
        "deadline",
        datetime(2026, 9, 1, tzinfo=UTC),
    )
    project.deleted_at = overrides.get("deleted_at")
    return project


def _task(**overrides: object) -> Task:
    task = Task()
    task.id = overrides.get("id", uuid.uuid4())
    task.title = overrides.get("title", "Verify release")
    task.description = overrides.get("description", "Run the release gate")
    task.status = overrides.get("status", "in_progress")
    task.estimate_hours = overrides.get("estimate_hours", 3.0)
    task.context_tags = overrides.get("context_tags", ["quality"])
    return task


def _asset(**overrides: object) -> ContentAsset:
    asset = ContentAsset()
    asset.id = overrides.get("id", uuid.uuid4())
    asset.note_id = overrides.get("note_id")
    asset.project_id = overrides.get("project_id")
    asset.task_id = overrides.get("task_id")
    asset.title = overrides.get("title", "Launch source pack")
    asset.asset_type = overrides.get("asset_type", "notebooklm_podcast")
    asset.status = overrides.get("status", "ready")
    asset.source_pack = overrides.get("source_pack", {})
    asset.template_prompt = overrides.get("template_prompt")
    asset.run_notes = overrides.get("run_notes")
    asset.metadata_ = overrides.get("metadata", {})
    asset.deleted_at = overrides.get("deleted_at")
    asset.created_at = overrides.get("created_at", datetime(2026, 8, 1, tzinfo=UTC))
    asset.updated_at = overrides.get("updated_at", datetime(2026, 8, 1, tzinfo=UTC))
    return asset


def test_source_pack_helpers_preserve_lineage_and_safe_empty_defaults() -> None:
    note = _note(tags=None)
    project = _project(deadline=None, description=None)
    task = _task(context_tags=None, description=None)
    asset = _asset(note_id=note.id, project_id=project.id, task_id=task.id)

    assert _default_template_prompt("brief", "Launch") == (
        "Prepare the source material for 'Launch'."
    )
    assert "NotebookLM podcast" in _default_template_prompt(
        "notebooklm_podcast",
        "Launch",
    )
    assert _note_source_pack(note)["tags"] == []
    assert _project_source_pack(project)["deadline"] is None
    assert _task_source_pack(task)["context_tags"] == []

    pack = _build_source_pack(
        asset=asset,
        note=note,
        project=project,
        task=task,
    )
    assert [document["type"] for document in pack["documents"]] == [
        "note",
        "project",
        "task",
    ]
    assert pack["lineage"] == {
        "note_id": str(note.id),
        "project_id": str(project.id),
        "task_id": str(task.id),
    }
    assert pack["project"]["description"] is None
    assert pack["notebooklm_prompt"].startswith("Create a NotebookLM podcast")

    empty_pack = _build_source_pack(
        asset=_asset(
            asset_type="brief",
            note_id=None,
            project_id=None,
            task_id=None,
        ),
        note=None,
        project=None,
        task=None,
    )
    assert empty_pack["documents"] == []
    assert empty_pack["lineage"] == {
        "note_id": None,
        "project_id": None,
        "task_id": None,
    }
    assert "notebooklm_prompt" not in empty_pack


def test_source_pack_helpers_preserve_nonempty_optional_values() -> None:
    note = _note(tags=["one"])
    project = _project()
    task = _task(context_tags=["deep-work"])
    assert _note_source_pack(note)["tags"] == ["one"]
    assert _project_source_pack(project)["deadline"] == "2026-09-01T00:00:00+00:00"
    assert _task_source_pack(task)["context_tags"] == ["deep-work"]


@pytest.mark.asyncio
async def test_create_with_linked_records_generates_defaults_and_flushes_only() -> None:
    session = _session()
    note = _note()
    project = _project()
    task = _task()
    session.execute.side_effect = [
        _Result(one_or_none=note),
        _Result(one_or_none=project),
    ]
    session.get.return_value = task

    asset = await create_content_asset(
        session,
        title=None,
        asset_type="notebooklm_podcast",
        note_id=note.id,
        project_id=project.id,
        task_id=task.id,
    )

    assert asset.title == note.title
    assert asset.source_pack["note_id"] == str(note.id)
    assert asset.template_prompt.startswith("Create a NotebookLM podcast")
    assert asset.metadata_ == {}
    session.add.assert_called_once_with(asset)
    session.flush.assert_awaited_once()
    session.commit.assert_not_awaited()
    assert "notes.deleted_at IS NULL" in str(session.execute.await_args_list[0].args[0])
    assert "projects.deleted_at IS NULL" in str(session.execute.await_args_list[1].args[0])


@pytest.mark.asyncio
async def test_create_title_fallbacks_and_explicit_payload_precedence() -> None:
    project_session = _session()
    project = _project()
    project_session.execute.return_value = _Result(one_or_none=project)
    from_project = await create_content_asset(
        project_session,
        title=None,
        asset_type="brief",
        project_id=project.id,
    )
    assert from_project.title == project.title

    task_session = _session()
    task = _task()
    task_session.get.return_value = task
    from_task = await create_content_asset(
        task_session,
        title=None,
        asset_type="brief",
        task_id=task.id,
    )
    assert from_task.title == task.title

    explicit_session = _session()
    explicit_session.add = AsyncMock()
    explicit = await create_content_asset(
        explicit_session,
        title="Explicit title",
        asset_type="brief",
        source_pack={"source": "operator"},
        template_prompt="Custom prompt",
        run_notes="Review carefully",
        metadata={"audience": "public"},
    )
    assert explicit.title == "Explicit title"
    assert explicit.source_pack == {"source": "operator"}
    assert explicit.template_prompt == "Custom prompt"
    assert explicit.run_notes == "Review carefully"
    assert explicit.metadata_ == {"audience": "public"}
    explicit_session.add.assert_awaited_once_with(explicit)

    untitled = await create_content_asset(
        _session(),
        title=None,
        asset_type="brief",
    )
    assert untitled.title == "Untitled content asset"


@pytest.mark.asyncio
async def test_get_and_list_cover_live_empty_and_all_filters() -> None:
    session = _session()
    asset = _asset()
    note_id = uuid.uuid4()
    session.execute.side_effect = [
        _Result(one_or_none=asset),
        _Result(one_or_none=None),
        _Result(one=1),
        _Result(rows=[asset]),
        _Result(one=0),
        _Result(rows=[]),
    ]

    assert await get_content_asset(session, asset.id) is asset
    assert await get_content_asset(session, uuid.uuid4()) is None
    rows, total = await list_content_assets(
        session,
        asset_type="brief",
        status="ready",
        note_id=note_id,
        limit=7,
        offset=3,
    )
    assert rows == [asset]
    assert total == 1
    empty, empty_total = await list_content_assets(session)
    assert empty == []
    assert empty_total == 0

    get_sql = str(session.execute.await_args_list[0].args[0])
    filtered_count_sql = str(session.execute.await_args_list[2].args[0])
    assert "content_assets.deleted_at IS NULL" in get_sql
    assert "content_assets.asset_type" in filtered_count_sql
    assert "content_assets.status" in filtered_count_sql
    assert "content_assets.note_id" in filtered_count_sql


@pytest.mark.asyncio
async def test_update_covers_missing_all_fields_and_noop_flush_boundary() -> None:
    session = _session()
    asset = _asset()
    with patch(
        "src.app.persistence.repositories.content_assets.get_content_asset",
        new=AsyncMock(side_effect=[None, asset, asset]),
    ):
        with pytest.raises(ValueError, match="Content asset not found"):
            await update_content_asset(session, uuid.uuid4(), title="Missing")

        updated = await update_content_asset(
            session,
            asset.id,
            title="Updated",
            status="needs_review",
            source_pack={"documents": []},
            template_prompt="Updated prompt",
            run_notes="Updated notes",
            metadata={"reviewed": True},
        )
        assert updated is asset
        assert asset.title == "Updated"
        assert asset.status == "needs_review"
        assert asset.source_pack == {"documents": []}
        assert asset.template_prompt == "Updated prompt"
        assert asset.run_notes == "Updated notes"
        assert asset.metadata_ == {"reviewed": True}

        assert await update_content_asset(session, asset.id) is asset

    assert session.flush.await_count == 2
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_source_pack_covers_missing_linked_and_unlinked_assets() -> None:
    session = _session()
    note = _note()
    project = _project()
    task = _task()
    linked = _asset(
        note_id=note.id,
        project_id=project.id,
        task_id=task.id,
        metadata={"existing": True},
    )
    unlinked = _asset(
        asset_type="brief",
        note_id=None,
        project_id=None,
        task_id=None,
        metadata=None,
    )

    with (
        patch(
            "src.app.persistence.repositories.content_assets.get_content_asset",
            new=AsyncMock(side_effect=[None, linked, unlinked]),
        ),
        patch(
            "src.app.persistence.repositories.content_assets._get_live_note",
            new=AsyncMock(return_value=note),
        ) as get_note,
        patch(
            "src.app.persistence.repositories.content_assets._get_live_project",
            new=AsyncMock(return_value=project),
        ) as get_project,
    ):
        with pytest.raises(ValueError, match="Content asset not found"):
            await generate_content_source_pack(session, uuid.uuid4())

        session.get.return_value = task
        generated = await generate_content_source_pack(session, linked.id)
        assert generated.source_pack["primary_note"]["title"] == note.title
        assert generated.source_pack["project"]["title"] == project.title
        assert generated.source_pack["task"]["title"] == task.title
        assert generated.metadata_["existing"] is True
        assert "source_pack_generated_at" in generated.metadata_

        generated_empty = await generate_content_source_pack(session, unlinked.id)
        assert generated_empty.source_pack["documents"] == []
        assert set(generated_empty.metadata_) == {"source_pack_generated_at"}

    get_note.assert_awaited_once_with(session, note.id)
    get_project.assert_awaited_once_with(session, project.id)
    session.get.assert_awaited_once_with(Task, task.id)
    assert session.flush.await_count == 2


@pytest.mark.asyncio
async def test_flush_failure_propagates_without_commit() -> None:
    session = _session()
    session.flush.side_effect = RuntimeError("write failed")
    with pytest.raises(RuntimeError, match="write failed"):
        await create_content_asset(
            session,
            title="Failure",
            asset_type="brief",
        )
    session.commit.assert_not_awaited()

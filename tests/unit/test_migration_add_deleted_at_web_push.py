"""Tests for the 2026-04-18 migration adding `deleted_at` to web_push_subscriptions.

Validates:
1. The migration module loads, exposes the expected revision IDs, and chains
   onto the previous head (009 web_push_subscriptions / c9d0e1f2a3b4).
2. The upgrade is idempotent — running against a schema that already has the
   column / partial index should be a no-op.
3. The upgrade is wired to add a partial index `WHERE deleted_at IS NULL`.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "src/app/persistence/migrations/versions"
    / "2026_04_18_1200_add_deleted_at_to_web_push_subscriptions.py"
)


@pytest.fixture
def migration_module():
    spec = importlib.util.spec_from_file_location(
        "_test_migration_add_deleted_at_web_push", MIGRATION_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def test_migration_metadata(migration_module) -> None:
    assert migration_module.revision == "d0e1f2a3b4c5"
    assert migration_module.down_revision == "c9d0e1f2a3b4"
    assert migration_module.branch_labels is None


def test_upgrade_adds_column_and_partial_index_when_missing(migration_module) -> None:
    """When the column does not exist, upgrade should add it AND the partial index."""
    add_column = MagicMock()
    execute = MagicMock()

    with (
        patch.object(migration_module, "_has_table", return_value=True),
        patch.object(migration_module, "_has_column", return_value=False),
        patch.object(migration_module, "_has_index", return_value=False),
        patch.object(migration_module.op, "add_column", add_column),
        patch.object(migration_module.op, "execute", execute),
    ):
        migration_module.upgrade()

    add_column.assert_called_once()
    args, _ = add_column.call_args
    assert args[0] == "web_push_subscriptions"
    column = args[1]
    assert column.name == "deleted_at"
    assert column.nullable is True

    execute.assert_called_once()
    sql_text = str(execute.call_args.args[0])
    assert "ix_web_push_subscriptions_deleted_at_null" in sql_text
    assert "WHERE deleted_at IS NULL" in sql_text


def test_upgrade_is_idempotent_when_column_present(migration_module) -> None:
    """If column + index already exist, upgrade should not call add_column / execute."""
    add_column = MagicMock()
    execute = MagicMock()

    with (
        patch.object(migration_module, "_has_table", return_value=True),
        patch.object(migration_module, "_has_column", return_value=True),
        patch.object(migration_module, "_has_index", return_value=True),
        patch.object(migration_module.op, "add_column", add_column),
        patch.object(migration_module.op, "execute", execute),
    ):
        migration_module.upgrade()

    add_column.assert_not_called()
    execute.assert_not_called()


def test_upgrade_skips_when_table_missing(migration_module) -> None:
    add_column = MagicMock()
    execute = MagicMock()

    with (
        patch.object(migration_module, "_has_table", return_value=False),
        patch.object(migration_module.op, "add_column", add_column),
        patch.object(migration_module.op, "execute", execute),
    ):
        migration_module.upgrade()

    add_column.assert_not_called()
    execute.assert_not_called()


def test_downgrade_drops_partial_index_and_column(migration_module) -> None:
    drop_column = MagicMock()
    execute = MagicMock()

    has_index_calls: dict[str, bool] = {
        "ix_web_push_subscriptions_deleted_at_null": True,
        "ix_web_push_subscriptions_deleted_at": False,  # legacy not present
    }

    def fake_has_index(_table: str, name: str) -> bool:
        return has_index_calls.get(name, False)

    with (
        patch.object(migration_module, "_has_table", return_value=True),
        patch.object(migration_module, "_has_column", return_value=True),
        patch.object(migration_module, "_has_index", side_effect=fake_has_index),
        patch.object(migration_module.op, "drop_column", drop_column),
        patch.object(migration_module.op, "execute", execute),
    ):
        migration_module.downgrade()

    execute.assert_called_once()
    assert "DROP INDEX IF EXISTS ix_web_push_subscriptions_deleted_at_null" in str(
        execute.call_args.args[0]
    )
    drop_column.assert_called_once_with("web_push_subscriptions", "deleted_at")


def test_orm_model_still_declares_deleted_at_via_softdeletemixin() -> None:
    """Sanity check: the ORM contract that motivated the migration still holds."""
    from src.app.persistence.models import SoftDeleteMixin, WebPushSubscription

    assert issubclass(WebPushSubscription, SoftDeleteMixin)
    assert "deleted_at" in WebPushSubscription.__table__.columns
    assert WebPushSubscription.__table__.columns["deleted_at"].nullable is True

"""Shared declarative base, tenancy scope, and soft-delete helpers."""

import uuid
from datetime import datetime

from sqlalchemy import ColumnElement, DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all ORM models."""


class SoftDeleteMixin:
    """Mixin that adds soft-delete support via a deleted_at timestamp.

    Models using this mixin are not physically deleted — instead, deleted_at
    is set to the current UTC time. Query-level filtering should be applied
    by the caller or via repository helpers.
    """

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        index=True,
    )

    def soft_delete(self) -> None:
        """Mark this record as soft-deleted."""
        from datetime import UTC

        self.deleted_at = datetime.now(UTC)

    def restore(self) -> None:
        """Restore a soft-deleted record."""
        self.deleted_at = None

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


DEFAULT_ACCOUNT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEFAULT_OWNER_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")


class AccountScopedMixin:
    """Mixin for customer-owned rows during the SaaS tenancy migration.

    The default account keeps existing single-user write paths working while
    routes and repositories are progressively moved to explicit principals.
    """

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        default=DEFAULT_ACCOUNT_ID,
        server_default=text(f"'{DEFAULT_ACCOUNT_ID}'::uuid"),
        index=True,
    )


def not_deleted(model_class: type[SoftDeleteMixin]) -> ColumnElement[bool]:
    """Filter condition for excluding soft-deleted rows."""
    return model_class.deleted_at.is_(None)

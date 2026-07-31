"""Async database engine and session factory."""

from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from src.app.persistence.models import AccountScopedMixin

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _tenant_account_id(session: Session) -> Any | None:
    """Return the active account scope for this ORM session, if one is set."""
    return session.info.get("account_id")


@event.listens_for(Session, "do_orm_execute")
def _add_account_scope_to_selects(execute_state: ORMExecuteState) -> None:
    """Constrain ORM SELECTs for account-scoped models to the active account."""
    if not execute_state.is_select:
        return
    if execute_state.execution_options.get("skip_account_scope"):
        return

    account_id = _tenant_account_id(execute_state.session)
    if account_id is None:
        return

    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            AccountScopedMixin,
            lambda cls: cls.account_id == account_id,
            include_aliases=True,
        )
    )


@event.listens_for(Session, "before_flush")
def _guard_account_scoped_flushes(
    session: Session,
    _flush_context: object,
    _instances: object,
) -> None:
    """Stamp new account-scoped rows and reject cross-account mutations."""
    account_id = _tenant_account_id(session)
    if account_id is None:
        return

    for obj in session.new:
        if isinstance(obj, AccountScopedMixin) and getattr(obj, "account_id", None) is None:
            obj.account_id = account_id

    for obj in [*session.dirty, *session.deleted]:
        if not isinstance(obj, AccountScopedMixin):
            continue
        object_account_id = getattr(obj, "account_id", None)
        if object_account_id is not None and object_account_id != account_id:
            msg = f"Cross-account mutation blocked for {type(obj).__name__}"
            raise RuntimeError(msg)


@event.listens_for(Session, "after_begin")
def _set_postgres_account_settings(
    session: Session,
    _transaction: object,
    connection: Any,
) -> None:
    """Expose account/user IDs to Postgres RLS policies for this transaction."""
    account_id = _tenant_account_id(session)
    if account_id is None:
        return

    user_id = session.info.get("user_id")
    connection.execute(
        text(
            "SELECT "
            "set_config('app.account_id', :account_id, true), "
            "set_config('app.user_id', :user_id, true)"
        ),
        {
            "account_id": str(account_id),
            "user_id": "" if user_id is None else str(user_id),
        },
    )


def init_engine(database_url: str) -> AsyncEngine:
    """Create the async engine. Called once at app startup."""
    from src.app.config import get_settings

    settings = get_settings()

    global _engine
    connect_args = {"statement_cache_size": 0} if settings.db_pgbouncer_mode else {}
    _engine = create_async_engine(
        database_url,
        echo=False,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_pool_max_overflow,
        pool_recycle=settings.db_pool_recycle,
        pool_pre_ping=True,
        # Transaction-mode PgBouncer cannot use prepared statements. Native
        # PostgreSQL should retain asyncpg's statement cache for performance.
        connect_args=connect_args,
    )
    return _engine


def get_engine() -> AsyncEngine:
    """Get the engine. Crashes if init_engine() was not called."""
    if _engine is None:
        msg = "Database engine not initialised. Call init_engine() first."
        raise RuntimeError(msg)
    return _engine


def init_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create sessions pre-scoped to the self-hosted owner's account.

    API authentication replaces these defaults with the verified principal.
    Background jobs use the same single-owner scope so PostgreSQL RLS remains
    effective under the least-privilege runtime role.
    """
    from src.app.config import get_settings

    settings = get_settings()
    global _session_factory
    _session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        info={
            "account_id": UUID(str(settings.first_account_id)),
            "user_id": UUID(str(settings.first_owner_user_id)),
        },
    )
    return _session_factory


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide session factory for ``async with`` usage.

    The FastAPI dependency :func:`get_session` yields a *single* session
    suitable for one request, but some call sites (the API-key auth
    dependency, CLI scripts) need to open their own scoped session without
    participating in the request's session lifecycle. This helper exposes
    the factory so they can do so without reaching into the module-private
    ``_session_factory``.
    """
    if _session_factory is None:
        msg = "Session factory not initialised. Call init_session_factory() first."
        raise RuntimeError(msg)
    return _session_factory


async def get_session() -> AsyncGenerator[AsyncSession]:
    """Yield a database session. For use as a FastAPI dependency."""
    if _session_factory is None:
        msg = "Session factory not initialised. Call init_session_factory() first."
        raise RuntimeError(msg)
    async with _session_factory() as session:
        yield session


async def close_engine() -> None:
    """Dispose of the engine. Called at app shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None

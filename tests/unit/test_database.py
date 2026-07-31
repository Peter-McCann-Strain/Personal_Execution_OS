"""Tests for database engine and session lifecycle."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import src.app.persistence.database as db_module
from src.app.persistence.database import (
    _add_account_scope_to_selects,
    _guard_account_scoped_flushes,
    _set_postgres_account_settings,
    close_engine,
    get_engine,
    get_session,
    init_engine,
    init_session_factory,
)
from src.app.persistence.models import Goal


@pytest.fixture(autouse=True)
def _reset_db_state():
    """Reset module-level engine/session state before and after each test."""
    original_engine = db_module._engine
    original_factory = db_module._session_factory
    db_module._engine = None
    db_module._session_factory = None
    yield
    db_module._engine = original_engine
    db_module._session_factory = original_factory


# ------------------------------------------------------------------
# get_engine / get_session — uninitialised
# ------------------------------------------------------------------


def test_get_engine_not_initialized():
    """get_engine raises RuntimeError when engine has not been initialised."""
    with pytest.raises(RuntimeError, match="Database engine not initialised"):
        get_engine()


async def test_get_session_not_initialized():
    """get_session raises RuntimeError when session factory has not been initialised."""
    with pytest.raises(RuntimeError, match="Session factory not initialised"):
        async for _ in get_session():
            pass


# ------------------------------------------------------------------
# init_engine
# ------------------------------------------------------------------


def test_init_engine_creates_engine():
    """init_engine should create and return an engine, and store it at module level."""
    mock_engine = MagicMock()
    mock_settings = MagicMock()
    mock_settings.db_pool_size = 5
    mock_settings.db_pool_max_overflow = 10
    mock_settings.db_pool_recycle = 300

    with (
        patch(
            "src.app.persistence.database.create_async_engine",
            return_value=mock_engine,
        ) as mock_create,
        patch(
            "src.app.config.get_settings",
            return_value=mock_settings,
        ),
    ):
        engine = init_engine("postgresql+asyncpg://user:pass@localhost:5432/db")

    assert engine is mock_engine
    assert db_module._engine is mock_engine
    mock_create.assert_called_once_with(
        "postgresql+asyncpg://user:pass@localhost:5432/db",
        echo=False,
        pool_size=5,
        max_overflow=10,
        pool_recycle=300,
        pool_pre_ping=True,
        connect_args={"statement_cache_size": 0},
    )


def test_init_engine_get_engine_roundtrip():
    """After init_engine, get_engine returns the same engine."""
    mock_engine = MagicMock()
    mock_settings = MagicMock()
    mock_settings.db_pool_size = 5
    mock_settings.db_pool_max_overflow = 10
    mock_settings.db_pool_recycle = 300

    with (
        patch(
            "src.app.persistence.database.create_async_engine",
            return_value=mock_engine,
        ),
        patch(
            "src.app.config.get_settings",
            return_value=mock_settings,
        ),
    ):
        init_engine("postgresql+asyncpg://fake")

    assert get_engine() is mock_engine


# ------------------------------------------------------------------
# init_session_factory
# ------------------------------------------------------------------


def test_init_session_factory_returns_factory():
    """init_session_factory should return a session factory and store it."""
    mock_engine = MagicMock()

    with patch(
        "src.app.persistence.database.async_sessionmaker",
    ) as mock_maker:
        mock_factory = MagicMock()
        mock_maker.return_value = mock_factory
        factory = init_session_factory(mock_engine)

    assert factory is mock_factory
    assert db_module._session_factory is mock_factory


def test_init_session_factory_configures_correctly():
    """init_session_factory passes correct options to async_sessionmaker."""
    mock_engine = MagicMock()

    with patch(
        "src.app.persistence.database.async_sessionmaker",
    ) as mock_maker:
        init_session_factory(mock_engine)

    mock_maker.assert_called_once_with(
        mock_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        info={
            "account_id": uuid.UUID("00000000-0000-0000-0000-000000000001"),
            "user_id": uuid.UUID("00000000-0000-0000-0000-000000000010"),
        },
    )


# ------------------------------------------------------------------
# get_session — initialised
# ------------------------------------------------------------------


async def test_get_session_yields_session():
    """get_session yields a session when factory is initialised."""
    mock_session = AsyncMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    db_module._session_factory = mock_factory

    sessions = []
    async for session in get_session():
        sessions.append(session)

    assert len(sessions) == 1
    assert sessions[0] is mock_session


# ------------------------------------------------------------------
# close_engine
# ------------------------------------------------------------------


async def test_close_engine_cleans_up():
    """After close_engine, engine and factory are reset to None."""
    mock_engine = AsyncMock()
    db_module._engine = mock_engine
    db_module._session_factory = MagicMock()

    await close_engine()

    assert db_module._engine is None
    assert db_module._session_factory is None
    mock_engine.dispose.assert_awaited_once()


async def test_close_engine_noop_when_not_initialized():
    """close_engine should be a no-op when engine is None."""
    assert db_module._engine is None
    assert db_module._session_factory is None

    await close_engine()

    assert db_module._engine is None
    assert db_module._session_factory is None


# ------------------------------------------------------------------
# get_session — async generator lifecycle
# ------------------------------------------------------------------


async def test_get_session_generator_yields_and_exits():
    """get_session should yield exactly one session and clean up via the context manager."""
    mock_session = AsyncMock()

    # Create a proper async context manager
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    mock_factory = MagicMock()
    mock_factory.return_value = mock_cm

    db_module._session_factory = mock_factory

    sessions = []
    async for session in get_session():
        sessions.append(session)

    assert len(sessions) == 1
    assert sessions[0] is mock_session
    # The context manager's __aexit__ should have been called
    mock_cm.__aexit__.assert_awaited_once()


async def test_get_session_propagates_exception():
    """If code using the session raises, the exception should propagate."""
    mock_session = AsyncMock()

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    mock_factory = MagicMock()
    mock_factory.return_value = mock_cm

    db_module._session_factory = mock_factory

    with pytest.raises(ValueError, match="test error"):
        async for _session in get_session():
            raise ValueError("test error")


# ------------------------------------------------------------------
# close_engine — detailed lifecycle
# ------------------------------------------------------------------


async def test_close_engine_disposes_and_resets():
    """close_engine should dispose the engine and reset both module-level vars."""
    mock_engine = AsyncMock()
    mock_factory = MagicMock()

    db_module._engine = mock_engine
    db_module._session_factory = mock_factory

    await close_engine()

    mock_engine.dispose.assert_awaited_once()
    assert db_module._engine is None
    assert db_module._session_factory is None


async def test_close_engine_idempotent():
    """Calling close_engine multiple times should be safe."""
    mock_engine = AsyncMock()
    db_module._engine = mock_engine
    db_module._session_factory = MagicMock()

    await close_engine()
    await close_engine()  # second call is a no-op

    mock_engine.dispose.assert_awaited_once()
    assert db_module._engine is None


def test_tenant_guard_stamps_new_account_scoped_rows() -> None:
    account_id = uuid.uuid4()
    goal = Goal(title="Tenant stamped goal")
    session = MagicMock()
    session.info = {"account_id": account_id}
    session.new = [goal]
    session.dirty = []
    session.deleted = []

    _guard_account_scoped_flushes(session, None, None)

    assert goal.account_id == account_id


def test_tenant_guard_blocks_cross_account_mutation() -> None:
    account_id = uuid.uuid4()
    other_account_id = uuid.uuid4()
    goal = Goal(title="Wrong tenant goal", account_id=other_account_id)
    session = MagicMock()
    session.info = {"account_id": account_id}
    session.new = []
    session.dirty = [goal]
    session.deleted = []

    with pytest.raises(RuntimeError, match="Cross-account mutation blocked"):
        _guard_account_scoped_flushes(session, None, None)


def test_tenant_scope_adds_loader_criteria_to_selects() -> None:
    state = MagicMock()
    state.is_select = True
    state.execution_options = {}
    state.session.info = {"account_id": uuid.uuid4()}
    original_statement = select(Goal)
    state.statement = original_statement

    _add_account_scope_to_selects(state)

    assert state.statement is not original_statement


def test_tenant_scope_sets_postgres_transaction_settings() -> None:
    account_id = uuid.uuid4()
    user_id = uuid.uuid4()
    session = MagicMock()
    session.info = {"account_id": account_id, "user_id": user_id}
    connection = MagicMock()

    _set_postgres_account_settings(session, None, connection)

    connection.execute.assert_called_once()
    params = connection.execute.call_args.args[1]
    assert params == {"account_id": str(account_id), "user_id": str(user_id)}

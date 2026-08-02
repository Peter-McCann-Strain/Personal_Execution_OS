"""Unit tests for transaction-scoped pgvector HNSW tuning."""

from __future__ import annotations

from types import TracebackType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.persistence import vector_search
from src.app.persistence.vector_search import (
    Preset,
    ef_search_scope,
    hnsw_ef_search,
)


class _Transaction:
    """Record async transaction entry and exit without a database."""

    def __init__(self) -> None:
        self.entered = False
        self.exit_details: (
            tuple[
                type[BaseException] | None,
                BaseException | None,
                TracebackType | None,
            ]
            | None
        ) = None

    async def __aenter__(self) -> _Transaction:
        self.entered = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        self.exit_details = (exc_type, exc_value, traceback)
        return False


def _session(*, in_transaction: bool = False) -> MagicMock:
    session = MagicMock()
    session.in_transaction = MagicMock(return_value=in_transaction)
    session.execute = AsyncMock()
    session.begin = MagicMock()
    return session


def test_presets_make_the_supported_latency_recall_tradeoffs_explicit() -> None:
    assert Preset.MEMORY == 20
    assert Preset.DEFAULT == 40
    assert Preset.RESEARCH == 80
    assert list(Preset) == [Preset.MEMORY, Preset.DEFAULT, Preset.RESEARCH]


@pytest.mark.parametrize(
    ("preset", "expected"),
    [
        (Preset.MEMORY, 20),
        (Preset.DEFAULT, 40),
        (Preset.RESEARCH, 80),
        (1, 1),
        (1000, 1000),
    ],
)
async def test_hnsw_ef_search_executes_only_the_validated_integer(
    preset: Preset | int,
    expected: int,
) -> None:
    session = _session()

    with patch.object(vector_search.logger, "debug") as debug:
        await hnsw_ef_search(session, preset)

    statement = session.execute.await_args.args[0]
    assert str(statement) == f"SET LOCAL hnsw.ef_search = {expected}"
    assert statement.compile().params == {}
    session.execute.assert_awaited_once()
    session.begin.assert_not_called()
    debug.assert_called_once_with("hnsw_ef_search_set", ef_search=expected)


@pytest.mark.parametrize("invalid", [0, -1, 1001, 10_000])
async def test_hnsw_ef_search_rejects_out_of_range_values_before_sql(
    invalid: int,
) -> None:
    session = _session()

    with pytest.raises(
        ValueError,
        match=rf"hnsw\.ef_search must be in \[1, 1000\]; got {invalid}",
    ):
        await hnsw_ef_search(session, invalid)

    session.execute.assert_not_awaited()


async def test_hnsw_ef_search_propagates_invalid_conversion_before_sql() -> None:
    session = _session()

    with pytest.raises(ValueError, match="invalid literal"):
        await hnsw_ef_search(session, "not-an-integer")  # type: ignore[arg-type]

    session.execute.assert_not_awaited()


async def test_hnsw_ef_search_propagates_database_failure_without_logging_success() -> None:
    session = _session()
    failure = RuntimeError("database connection lost")
    session.execute.side_effect = failure

    with (
        patch.object(vector_search.logger, "debug") as debug,
        pytest.raises(RuntimeError, match="database connection lost") as raised,
    ):
        await hnsw_ef_search(session, Preset.DEFAULT)

    assert raised.value is failure
    session.execute.assert_awaited_once()
    debug.assert_not_called()


async def test_scope_reuses_an_active_transaction_without_taking_ownership() -> None:
    session = _session(in_transaction=True)
    events: list[str] = []

    async def apply_preset(actual_session: MagicMock, preset: Preset | int) -> None:
        assert actual_session is session
        assert preset is Preset.RESEARCH
        events.append("preset")

    with patch.object(vector_search, "hnsw_ef_search", side_effect=apply_preset) as setter:
        async with ef_search_scope(session, Preset.RESEARCH):
            events.append("body")

    assert events == ["preset", "body"]
    session.in_transaction.assert_called_once_with()
    session.begin.assert_not_called()
    setter.assert_awaited_once_with(session, Preset.RESEARCH)


async def test_scope_does_not_swallow_body_errors_in_an_active_transaction() -> None:
    session = _session(in_transaction=True)
    failure = LookupError("caller failed")

    with (
        patch.object(vector_search, "hnsw_ef_search", new=AsyncMock()) as setter,
        pytest.raises(LookupError, match="caller failed") as raised,
    ):
        async with ef_search_scope(session, Preset.MEMORY):
            raise failure

    assert raised.value is failure
    setter.assert_awaited_once_with(session, Preset.MEMORY)
    session.begin.assert_not_called()


async def test_scope_opens_and_cleanly_exits_a_transaction_when_needed() -> None:
    session = _session(in_transaction=False)
    transaction = _Transaction()
    session.begin.return_value = transaction

    with patch.object(vector_search, "hnsw_ef_search", new=AsyncMock()) as setter:
        async with ef_search_scope(session, Preset.DEFAULT):
            assert transaction.entered
            assert transaction.exit_details is None

    assert transaction.exit_details == (None, None, None)
    session.in_transaction.assert_called_once_with()
    session.begin.assert_called_once_with()
    setter.assert_awaited_once_with(session, Preset.DEFAULT)


async def test_scope_delegates_body_error_cleanup_to_its_owned_transaction() -> None:
    session = _session(in_transaction=False)
    transaction = _Transaction()
    session.begin.return_value = transaction
    failure = RuntimeError("query failed")

    with (
        patch.object(vector_search, "hnsw_ef_search", new=AsyncMock()) as setter,
        pytest.raises(RuntimeError, match="query failed") as raised,
    ):
        async with ef_search_scope(session, Preset.DEFAULT):
            raise failure

    assert raised.value is failure
    assert transaction.exit_details is not None
    assert transaction.exit_details[:2] == (RuntimeError, failure)
    assert transaction.exit_details[2] is not None
    setter.assert_awaited_once_with(session, Preset.DEFAULT)


async def test_scope_exits_its_owned_transaction_when_setting_the_preset_fails() -> None:
    session = _session(in_transaction=False)
    transaction = _Transaction()
    session.begin.return_value = transaction
    failure = RuntimeError("SET LOCAL failed")

    with (
        patch.object(
            vector_search,
            "hnsw_ef_search",
            new=AsyncMock(side_effect=failure),
        ) as setter,
        pytest.raises(RuntimeError, match="SET LOCAL failed") as raised,
    ):
        async with ef_search_scope(session, Preset.RESEARCH):
            pytest.fail("the protected block must not run")

    assert raised.value is failure
    assert transaction.entered
    assert transaction.exit_details is not None
    assert transaction.exit_details[:2] == (RuntimeError, failure)
    setter.assert_awaited_once_with(session, Preset.RESEARCH)

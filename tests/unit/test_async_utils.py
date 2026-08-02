"""Adversarial tests for sync/async database adapter boundaries."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.core.async_utils import affected_rows, mapping_rows, maybe_await


async def test_maybe_await_preserves_plain_values_and_resolves_awaitables() -> None:
    assert await maybe_await({"plain": True}) == {"plain": True}
    assert await maybe_await(AsyncMock(return_value="resolved")()) == "resolved"


async def test_mapping_rows_accepts_sync_and_async_sqlalchemy_shaped_results() -> None:
    sync_result = MagicMock()
    sync_result.mappings.return_value.all.return_value = [{"id": 1}, {"id": 2}]
    assert await mapping_rows(sync_result) == [{"id": 1}, {"id": 2}]

    async_result = MagicMock()
    mappings = MagicMock()
    mappings.all = AsyncMock(return_value=[{"id": 3}])
    async_result.mappings = AsyncMock(return_value=mappings)
    assert await mapping_rows(async_result) == [{"id": 3}]


@pytest.mark.parametrize(
    ("result", "message"),
    [
        (object(), r"callable mappings\(\)"),
        (
            MagicMock(mappings=MagicMock(return_value=object())),
            r"callable all\(\)",
        ),
    ],
)
async def test_mapping_rows_rejects_missing_adapter_methods(
    result: object,
    message: str,
) -> None:
    with pytest.raises(TypeError, match=message):
        await mapping_rows(result)


async def test_mapping_rows_rejects_malformed_collections_and_rows() -> None:
    non_iterable = MagicMock()
    non_iterable.mappings.return_value.all.return_value = 42
    with pytest.raises(TypeError, match=r"all\(\) did not return an iterable"):
        await mapping_rows(non_iterable)

    non_mapping_row = MagicMock()
    non_mapping_row.mappings.return_value.all.return_value = ["not-a-mapping"]
    with pytest.raises(TypeError, match="row is not a mapping"):
        await mapping_rows(non_mapping_row)

    non_string_key = MagicMock()
    non_string_key.mappings.return_value.all.return_value = [{1: "value"}]
    with pytest.raises(TypeError, match="non-string key"):
        await mapping_rows(non_string_key)


@pytest.mark.parametrize(
    ("rowcount", "expected"),
    [
        (7, 7),
        (1, 1),
        (0, 0),
        (-1, 0),
        (None, 0),
        (True, 0),
        ("4", 0),
    ],
)
def test_affected_rows_accepts_only_trustworthy_positive_integers(
    rowcount: object,
    expected: int,
) -> None:
    result = MagicMock()
    result.rowcount = rowcount
    assert affected_rows(result) == expected


def test_affected_rows_handles_results_without_cursor_metadata() -> None:
    assert affected_rows(object()) == 0

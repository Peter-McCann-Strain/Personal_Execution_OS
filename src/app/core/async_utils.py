"""Small helpers for code paths that may receive sync or async test doubles."""

from __future__ import annotations

from collections.abc import Awaitable, Iterable, Mapping
from typing import overload


@overload
async def maybe_await[T](value: Awaitable[T]) -> T: ...


@overload
async def maybe_await[T](value: T) -> T: ...


async def maybe_await(value: object) -> object:
    """Await a value when needed, otherwise return it unchanged."""
    if isinstance(value, Awaitable):
        return await value
    return value


async def mapping_rows(result: object) -> list[dict[str, object]]:
    """Return ``result.mappings().all()`` for both SQLAlchemy results and AsyncMocks."""
    mappings_method = getattr(result, "mappings", None)
    if not callable(mappings_method):
        raise TypeError("database result does not provide callable mappings()")
    mappings = await maybe_await(mappings_method())

    all_method = getattr(mappings, "all", None)
    if not callable(all_method):
        raise TypeError("database mapping result does not provide callable all()")
    rows = await maybe_await(all_method())
    if not isinstance(rows, Iterable):
        raise TypeError("database mapping result all() did not return an iterable")

    normalized: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError("database mapping row is not a mapping")
        if not all(isinstance(key, str) for key in row):
            raise TypeError("database mapping row contains a non-string key")
        normalized.append({key: value for key, value in row.items() if isinstance(key, str)})
    return normalized


def affected_rows(result: object) -> int:
    """Return a trustworthy positive DML row count, otherwise zero.

    SQLAlchemy exposes ``rowcount`` only on cursor-backed results, and DBAPI
    drivers may report ``-1`` when the count is unknown. Neither an unknown
    count nor a malformed test double should be treated as a successful write.
    """
    rowcount = getattr(result, "rowcount", None)
    if isinstance(rowcount, bool) or not isinstance(rowcount, int):
        return 0
    return max(0, rowcount)

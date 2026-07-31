"""Small helpers for code paths that may receive sync or async test doubles."""

from __future__ import annotations

from inspect import isawaitable
from typing import TypeVar

T = TypeVar("T")


async def maybe_await(value: T) -> T:
    """Await a value when needed, otherwise return it unchanged."""
    if isawaitable(value):
        return await value
    return value


async def mapping_rows(result: object) -> list:
    """Return ``result.mappings().all()`` for both SQLAlchemy results and AsyncMocks."""
    mappings = await maybe_await(result.mappings())
    rows = await maybe_await(mappings.all())
    return list(rows)

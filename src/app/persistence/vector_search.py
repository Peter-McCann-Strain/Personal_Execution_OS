"""Query-time tuning helpers for pgvector HNSW searches.

``hnsw.ef_search`` is a per-session GUC that trades recall for latency.
It must be set on the same connection that runs the vector query, and
``SET LOCAL`` keeps the change scoped to the enclosing transaction so
sibling sessions aren't affected.

Two presets are defined here, matching the agent-specific expectations
laid out in research/17_WORLD_CLASS_PLAN_V2.md:

* ``Preset.MEMORY`` (``ef_search = 20``) — latency-sensitive paths such as
  the Memory specialist's just-in-time recall. We tolerate ~5 % recall
  loss in exchange for sub-10ms lookups.
* ``Preset.RESEARCH`` (``ef_search = 80``) — recall-sensitive paths such
  as the Research specialist and weekly-review aggregators. We want near-
  exhaustive recall and can absorb the extra 10-30 ms.

``Preset.DEFAULT`` (``ef_search = 40``) matches pgvector 0.8.0's
recommended starting point and is used when no preset is specified.

Usage
-----

::

    from src.app.persistence.vector_search import (
        Preset,
        hnsw_ef_search,
    )

    async with session.begin():
        await hnsw_ef_search(session, Preset.MEMORY)
        rows = await session.execute(
            text("SELECT id FROM episodes "
                 "ORDER BY embedding <=> CAST(:q AS vector) LIMIT 10"),
            {"q": json.dumps(embedding, separators=(",", ":"))},
        )

Or as a context manager around an arbitrary block::

    async with ef_search_scope(session, Preset.RESEARCH):
        rows = await hybrid_search(session, query, embedding)

The module has zero runtime dependencies beyond SQLAlchemy and structlog
so it's safe to import from anywhere in ``src/app``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from enum import IntEnum

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


class Preset(IntEnum):
    """Named ``hnsw.ef_search`` values, one per agent workload profile."""

    # Latency-first: Memory specialist, interstitial journaling, anything
    # that must answer within a telegram-webhook budget.
    MEMORY = 20

    # pgvector 0.8.0 recommended default. Used when the caller does not
    # care which side of the recall/latency trade-off it sits on.
    DEFAULT = 40

    # Recall-first: Research specialist, weekly reviews, dataset builds.
    RESEARCH = 80


_MIN_EF_SEARCH = 1
# pgvector caps ef_search at 1000 in practice; values above that are
# rejected by the extension. We refuse them here to fail fast instead of
# bouncing off the backend with a generic SQL error.
_MAX_EF_SEARCH = 1000


async def hnsw_ef_search(session: AsyncSession, preset: Preset | int) -> None:
    """Set ``hnsw.ef_search`` for the current transaction.

    The session is expected to already have an active transaction — this
    function emits ``SET LOCAL`` which is a no-op outside of a transaction
    block. Call this immediately after opening the session's transaction
    and before running the vector query.

    Parameters
    ----------
    session:
        Active SQLAlchemy ``AsyncSession``.
    preset:
        Either a :class:`Preset` member or a raw integer. Integers are
        validated against pgvector's accepted range; out-of-range values
        raise :class:`ValueError` rather than silently clamping.
    """
    ef_value = int(preset)
    if ef_value < _MIN_EF_SEARCH or ef_value > _MAX_EF_SEARCH:
        msg = f"hnsw.ef_search must be in [{_MIN_EF_SEARCH}, {_MAX_EF_SEARCH}]; got {ef_value}"
        raise ValueError(msg)

    # SET LOCAL requires the value to be embeddable — ef_search is an
    # integer so it's safe to interpolate here without a bind parameter.
    # Postgres doesn't accept parameters in SET statements.
    await session.execute(text(f"SET LOCAL hnsw.ef_search = {ef_value}"))
    logger.debug("hnsw_ef_search_set", ef_search=ef_value)


@asynccontextmanager
async def ef_search_scope(
    session: AsyncSession,
    preset: Preset | int,
) -> AsyncIterator[None]:
    """Context manager that applies ``hnsw.ef_search`` for a block.

    If the session is not currently in a transaction, one is opened for
    the duration of the block so that ``SET LOCAL`` has an enclosing
    txn. If the session is already in a transaction, we reuse it.

    Example
    -------

    ::

        async with ef_search_scope(session, Preset.RESEARCH):
            rows = await hybrid_search(session, query, embedding)
    """
    if session.in_transaction():
        await hnsw_ef_search(session, preset)
        yield
        return

    async with session.begin():
        await hnsw_ef_search(session, preset)
        yield

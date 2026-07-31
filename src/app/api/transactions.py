"""Shared async transaction helpers for API routes."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from inspect import iscoroutine
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import SessionTransactionOrigin


@asynccontextmanager
async def session_transaction(session: AsyncSession) -> AsyncIterator[None]:
    """Open a transaction that works with both real sessions and AsyncMock tests."""
    active: Any = session.in_transaction()
    if iscoroutine(active):
        active = await active
    if bool(active):
        transaction: Any = session.get_transaction()
        if iscoroutine(transaction):
            transaction = await transaction
        sync_transaction = getattr(transaction, "sync_transaction", transaction)
        origin = getattr(sync_transaction, "origin", None)

        if isinstance(origin, SessionTransactionOrigin) and (
            origin is not SessionTransactionOrigin.AUTOBEGIN
        ):
            # The caller explicitly owns this transaction. Isolate our work in
            # a savepoint and leave the outer transaction open.
            nested: Any = session.begin_nested()
            if iscoroutine(nested):
                nested = await nested
            async with nested:
                yield
            return

        # SQLAlchemy auto-started this transaction on a validation read. The
        # route owns it and must commit or roll it back.
        try:
            yield
        except BaseException:
            await session.rollback()
            raise
        else:
            await session.commit()
        return

    # AsyncSessionTransaction is both awaitable and an async context manager,
    # but calling begin() on an AsyncMock returns a coroutine. Only await an
    # actual coroutine; awaiting SQLAlchemy's transaction and then entering it
    # starts the same transaction twice.
    transaction: Any = session.begin()
    if iscoroutine(transaction):
        transaction = await transaction
    async with transaction:
        yield

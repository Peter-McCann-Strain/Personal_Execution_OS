"""Real-Postgres integration tests for /api/episodes.

This is the pilot file for the testcontainers + pgvector migration
described in tests/integration/README.md. It mirrors a subset of
`test_api_endpoints.py::TestEpisodesListEndpoint` but hits a live
pgvector/pgvector:pg16 container instead of a mocked AsyncSession.

If Docker is unavailable, the session-scoped `postgres_container`
fixture `pytest.skip`s these tests cleanly.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.transactions import session_transaction
from src.app.persistence.models import Episode


class TestEpisodesListRealDb:
    """GET /api/episodes against a real pgvector Postgres container."""

    async def test_list_episodes_empty(self, db_integration_client):
        """With zero episodes in the DB the endpoint returns an empty page."""
        client, _session = db_integration_client

        response = await client.get("/api/episodes")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []
        assert data["has_more"] is False

    async def test_list_episodes_returns_inserted_rows(self, db_integration_client):
        """Inserted rows round-trip through the full route -> SQL -> DTO pipeline."""
        client, session = db_integration_client

        ep = Episode(
            id=uuid.uuid4(),
            content="Morning walk along the canal.",
            summary="Morning walk",
            episode_type="diary",
            para_category="area",
            mood_score=7.5,
            energy_rating=8.0,
            tags=["exercise", "morning"],
            people_mentioned=[],
            source="api",
        )
        session.add(ep)
        await session.flush()

        response = await client.get("/api/episodes", params={"limit": 10})

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        item = data["items"][0]
        assert item["content"] == "Morning walk along the canal."
        assert item["mood_score"] == pytest.approx(7.5)
        assert item["tags"] == ["exercise", "morning"]

    async def test_list_episodes_respects_pagination(self, db_integration_client):
        """`limit` and `offset` query params are honoured by real SQL."""
        client, session = db_integration_client

        for i in range(3):
            session.add(
                Episode(
                    id=uuid.uuid4(),
                    content=f"Entry {i}",
                    episode_type="diary",
                    source="api",
                )
            )
        await session.flush()

        response = await client.get("/api/episodes", params={"limit": 2, "offset": 0})

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert data["page"] == 1
        assert data["page_size"] == 2
        assert data["has_more"] is True
        assert len(data["items"]) == 2


async def test_session_transaction_adopts_autobegun_read_transaction(db_engine):
    """A read-before-write route must commit without a second begin()."""
    episode_id = uuid.uuid4()
    try:
        async with AsyncSession(db_engine, expire_on_commit=False) as session:
            await session.execute(text("SELECT 1"))
            assert session.in_transaction()

            async with session_transaction(session):
                session.add(
                    Episode(
                        id=episode_id,
                        content="Autobegin regression guard",
                        episode_type="diary",
                        source="api",
                    )
                )

        async with AsyncSession(db_engine) as verification:
            stored = await verification.scalar(select(Episode).where(Episode.id == episode_id))
            assert stored is not None
    finally:
        async with AsyncSession(db_engine) as cleanup:
            stored = await cleanup.get(Episode, episode_id)
            if stored is not None:
                await cleanup.delete(stored)
                await cleanup.commit()


async def test_session_transaction_preserves_explicit_outer_transaction(db_engine):
    """The helper must not commit a transaction owned by its caller."""
    episode_id = uuid.uuid4()
    async with (
        AsyncSession(
            db_engine,
            expire_on_commit=False,
        ) as session,
        session.begin(),
    ):
        async with session_transaction(session):
            session.add(
                Episode(
                    id=episode_id,
                    content="Nested ownership regression guard",
                    episode_type="diary",
                    source="api",
                )
            )
        assert session.in_transaction()
        assert await session.scalar(select(Episode).where(Episode.id == episode_id))
        await session.rollback()

    async with AsyncSession(db_engine) as verification:
        assert await verification.get(Episode, episode_id) is None

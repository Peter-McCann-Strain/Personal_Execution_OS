"""Integration tests for the Phase 7.3 idempotency layer.

The tests exercise the middleware end-to-end against a real FastAPI app with a
pgvector-backed Postgres container. A stand-in POST route is registered under
``/api/commitments`` via the existing commitments router, but the handler is
patched so we can observe exactly how many times it is invoked by the
middleware — i.e. duplicate requests should hit the cache rather than the
handler.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from src.app.api.idempotency import (
    _fingerprint,
    mark_idempotent,
    protected_routes,
)
from src.app.persistence.models import IdempotencyKey

pytestmark = pytest.mark.asyncio


def _make_commitment_mock(commitment_id: uuid.UUID | None = None):
    now = datetime.now(UTC)
    commitment = AsyncMock()
    commitment.id = commitment_id or uuid.uuid4()
    commitment.verbatim_text = "I'll send the report tomorrow."
    commitment.normalized_action = "Send the report"
    commitment.who_committed = "Alex"
    commitment.who_to = "Team"
    commitment.temporal_expression_raw = "tomorrow"
    commitment.temporal_normalized = None
    commitment.commitment_type = "promise"
    commitment.confidence_score = 0.92
    commitment.status = "detected"
    commitment.created_at = now
    commitment.updated_at = now
    return commitment


@pytest_asyncio.fixture
async def protected_client(db_integration_client):
    """Share the container-backed integration client with idempotency patches."""
    client, session = db_integration_client
    # The initial registration is done at module import, but a test suite run
    # earlier may have trimmed the set. Ensure our route is still marked.
    mark_idempotent("POST", "/api/commitments")
    yield client, session


async def test_same_key_same_body_returns_cached_response(protected_client):
    """Second request with identical key+body must skip the handler entirely."""
    client, session = protected_client
    call_count = 0

    async def fake_create(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return _make_commitment_mock()

    async def fake_refresh(*args, **kwargs):
        return None

    async def fake_reflection_pack_refresh(*args, **kwargs):
        return None

    payload = {
        "verbatim_text": "I'll send the report tomorrow.",
        "normalized_action": "Send the report",
        "who_committed": "Alex",
        "who_to": "Team",
        "temporal_expression": "tomorrow",
        "confidence_score": 0.92,
    }
    key = str(uuid.uuid4())
    headers = {"Idempotency-Key": key}

    with (
        patch(
            "src.app.api.routes.commitments.repo_create_commitment",
            new=fake_create,
        ),
        patch(
            "src.app.api.routes.commitments.enqueue_reflection_pack_refresh",
            new=fake_reflection_pack_refresh,
        ),
        patch.object(session, "refresh", new=fake_refresh),
    ):
        first = await client.post("/api/commitments", json=payload, headers=headers)
        second = await client.post("/api/commitments", json=payload, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json()
    assert second.headers.get("idempotent-replay") == "true"
    assert call_count == 1, "handler should only execute once for identical retries"


async def test_same_key_different_body_returns_conflict(protected_client):
    """Fingerprint mismatch must surface as 409 Conflict."""
    client, session = protected_client

    async def fake_create(*args, **kwargs):
        return _make_commitment_mock()

    async def fake_refresh(*args, **kwargs):
        return None

    async def fake_reflection_pack_refresh(*args, **kwargs):
        return None

    key = str(uuid.uuid4())
    headers = {"Idempotency-Key": key}

    payload_a = {
        "verbatim_text": "I'll send the report tomorrow.",
        "normalized_action": "Send the report",
        "who_committed": "Alex",
        "confidence_score": 0.9,
    }
    payload_b = {
        "verbatim_text": "I'll send a different report tomorrow.",
        "normalized_action": "Send a DIFFERENT report",
        "who_committed": "Alex",
        "confidence_score": 0.9,
    }

    with (
        patch(
            "src.app.api.routes.commitments.repo_create_commitment",
            new=fake_create,
        ),
        patch(
            "src.app.api.routes.commitments.enqueue_reflection_pack_refresh",
            new=fake_reflection_pack_refresh,
        ),
        patch.object(session, "refresh", new=fake_refresh),
    ):
        first = await client.post("/api/commitments", json=payload_a, headers=headers)
        conflict = await client.post("/api/commitments", json=payload_b, headers=headers)

    assert first.status_code == 201
    assert conflict.status_code == 409
    assert conflict.json()["error"] == "idempotency_key_conflict"


async def test_different_keys_run_handler_twice(protected_client):
    """Two distinct keys must both reach the handler."""
    client, session = protected_client
    call_count = 0

    async def fake_create(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return _make_commitment_mock()

    async def fake_refresh(*args, **kwargs):
        return None

    async def fake_reflection_pack_refresh(*args, **kwargs):
        return None

    payload = {
        "verbatim_text": "I'll send the report tomorrow.",
        "normalized_action": "Send the report",
        "who_committed": "Alex",
        "confidence_score": 0.9,
    }

    with (
        patch(
            "src.app.api.routes.commitments.repo_create_commitment",
            new=fake_create,
        ),
        patch(
            "src.app.api.routes.commitments.enqueue_reflection_pack_refresh",
            new=fake_reflection_pack_refresh,
        ),
        patch.object(session, "refresh", new=fake_refresh),
    ):
        r1 = await client.post(
            "/api/commitments",
            json=payload,
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        r2 = await client.post(
            "/api/commitments",
            json=payload,
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )

    assert r1.status_code == 201
    assert r2.status_code == 201
    assert call_count == 2


async def test_missing_header_returns_400(protected_client):
    """Registered routes must reject requests without an Idempotency-Key."""
    client, _session = protected_client
    response = await client.post(
        "/api/commitments",
        json={
            "verbatim_text": "foo",
            "normalized_action": "bar",
            "who_committed": "Alex",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "idempotency_key_required"


async def test_in_flight_duplicate_returns_conflict(protected_client):
    """Second arrival with a 'started' row (< 60s old) returns 409."""
    client, session = protected_client
    key = str(uuid.uuid4())

    # Seed a started row directly — we want to simulate "a concurrent request
    # is already running" without actually racing two handlers in the test.
    fingerprint = "fp-" + "a" * 60
    session.add(
        IdempotencyKey(
            key=key,
            request_fingerprint=fingerprint,
            recovery_point="started",
            method="POST",
            route="/api/commitments",
        )
    )
    await session.commit()

    response = await client.post(
        "/api/commitments",
        json={
            "verbatim_text": "foo",
            "normalized_action": "bar",
            "who_committed": "Alex",
        },
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 409
    assert response.json()["error"] in {
        "idempotency_in_flight",
        "idempotency_key_conflict",
    }


async def test_old_started_row_remains_blocked(protected_client):
    """Elapsed time must never cause a possibly-live action to execute twice."""
    client, session = protected_client
    call_count = 0

    async def fake_create(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return _make_commitment_mock()

    async def fake_refresh(*args, **kwargs):
        return None

    async def fake_reflection_pack_refresh(*args, **kwargs):
        return None

    key = str(uuid.uuid4())
    payload = {
        "verbatim_text": "I'll send the report tomorrow.",
        "normalized_action": "Send the report",
        "who_committed": "Alex",
    }

    # Build the exact fingerprint the middleware will compute so the replay
    # path does not trigger a conflict.
    import json as json_lib

    canonical_body = json_lib.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    fingerprint = _fingerprint("POST", "/api/commitments", canonical_body)

    stale_created = datetime.now(UTC) - timedelta(hours=2)
    session.add(
        IdempotencyKey(
            key=key,
            request_fingerprint=fingerprint,
            recovery_point="started",
            method="POST",
            route="/api/commitments",
            created_at=stale_created,
        )
    )
    await session.commit()

    with (
        patch(
            "src.app.api.routes.commitments.repo_create_commitment",
            new=fake_create,
        ),
        patch(
            "src.app.api.routes.commitments.enqueue_reflection_pack_refresh",
            new=fake_reflection_pack_refresh,
        ),
        patch.object(session, "refresh", new=fake_refresh),
    ):
        response = await client.post(
            "/api/commitments",
            json=payload,
            headers={"Idempotency-Key": key},
        )

    assert response.status_code == 409
    assert response.json()["error"] == "idempotency_in_flight"
    assert call_count == 0


async def test_expired_key_treated_as_new(protected_client):
    """Rows past their TTL are ignored — handler runs again."""
    client, session = protected_client
    call_count = 0

    async def fake_create(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return _make_commitment_mock()

    async def fake_refresh(*args, **kwargs):
        return None

    async def fake_reflection_pack_refresh(*args, **kwargs):
        return None

    key = str(uuid.uuid4())
    session.add(
        IdempotencyKey(
            key=key,
            request_fingerprint="stale-fp",
            recovery_point="completed",
            method="POST",
            route="/api/commitments",
            response_status=201,
            response_body={"ok": True},
            created_at=datetime.now(UTC) - timedelta(hours=26),
            expires_at=datetime.now(UTC) - timedelta(hours=2),
        )
    )
    await session.commit()

    with (
        patch(
            "src.app.api.routes.commitments.repo_create_commitment",
            new=fake_create,
        ),
        patch(
            "src.app.api.routes.commitments.enqueue_reflection_pack_refresh",
            new=fake_reflection_pack_refresh,
        ),
        patch.object(session, "refresh", new=fake_refresh),
    ):
        response = await client.post(
            "/api/commitments",
            json={
                "verbatim_text": "fresh",
                "normalized_action": "Send the report",
                "who_committed": "Alex",
            },
            headers={"Idempotency-Key": key},
        )

    # Expired row did not block — handler executed normally.
    assert response.status_code == 201
    assert call_count == 1


async def test_protected_routes_include_expected_entries():
    """Regression guard: the central registration list must cover the spec."""
    registered = set(protected_routes())
    spec_required = {
        ("POST", "/api/commitments"),
        ("POST", "/api/saved-memories"),
        ("POST", "/api/projects"),
        ("POST", "/api/goals"),
        ("POST", "/api/decisions"),
        ("POST", "/api/habits"),
        ("POST", "/api/notes"),
        ("POST", "/api/content-assets"),
    }
    missing = spec_required - registered
    assert not missing, f"idempotency registration missing: {missing}"


async def test_concurrent_duplicates_return_conflict(protected_client):
    """Two concurrent POSTs with the same key must produce a single commit."""
    client, session = protected_client
    handler_started = asyncio.Event()
    handler_release = asyncio.Event()
    call_count = 0

    async def fake_create(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        handler_started.set()
        await handler_release.wait()
        return _make_commitment_mock()

    async def fake_refresh(*args, **kwargs):
        return None

    async def fake_reflection_pack_refresh(*args, **kwargs):
        return None

    payload = {
        "verbatim_text": "foo",
        "normalized_action": "bar",
        "who_committed": "Alex",
    }
    key = str(uuid.uuid4())
    headers = {"Idempotency-Key": key}

    with (
        patch(
            "src.app.api.routes.commitments.repo_create_commitment",
            new=fake_create,
        ),
        patch(
            "src.app.api.routes.commitments.enqueue_reflection_pack_refresh",
            new=fake_reflection_pack_refresh,
        ),
        patch.object(session, "refresh", new=fake_refresh),
    ):
        first_task = asyncio.create_task(
            client.post("/api/commitments", json=payload, headers=headers)
        )
        await asyncio.wait_for(handler_started.wait(), timeout=5.0)

        # Second request arrives while the first is still in flight.
        second = await client.post("/api/commitments", json=payload, headers=headers)
        handler_release.set()
        first = await first_task

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error"] == "idempotency_in_flight"
    assert call_count == 1

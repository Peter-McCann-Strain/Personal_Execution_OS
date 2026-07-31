"""Unit tests for the idempotency registry + fingerprinting helpers.

The full replay/conflict semantics require a real database (see
``tests/integration/test_idempotency.py``). These tests keep the pure helpers
honest so a registration regression or a fingerprint mismatch in code review
is caught without spinning up a container.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.app.api.idempotency import (
    IDEMPOTENCY_HEADER,
    MAX_FINGERPRINT_BYTES,
    MAX_KEY_LENGTH,
    IdempotencyMiddleware,
    _fingerprint,
    is_protected,
    mark_idempotent,
    protected_routes,
)


def test_fingerprint_stable_for_same_input():
    """Hash must be deterministic — identical inputs => identical digest."""
    body = b'{"hello":"world"}'
    assert _fingerprint("POST", "/api/test", body) == _fingerprint("POST", "/api/test", body)


def test_fingerprint_differs_by_method():
    """Method is part of the digest so a key cannot cross-verb."""
    body = b'{"hello":"world"}'
    assert _fingerprint("POST", "/api/test", body) != _fingerprint("PUT", "/api/test", body)


def test_fingerprint_differs_by_path():
    """Different paths produce different digests."""
    body = b'{"hello":"world"}'
    assert _fingerprint("POST", "/api/a", body) != _fingerprint("POST", "/api/b", body)


def test_fingerprint_differs_by_body_bytes():
    """Body mutation flips the digest — underpins the 409 guarantee."""
    f1 = _fingerprint("POST", "/api/test", b'{"n":1}')
    f2 = _fingerprint("POST", "/api/test", b'{"n":2}')
    assert f1 != f2


def test_method_case_is_normalised():
    """Lowercase verbs fingerprint the same as uppercase."""
    body = b""
    assert _fingerprint("post", "/api/test", body) == _fingerprint("POST", "/api/test", body)


def test_registry_contains_all_spec_routes():
    """Regression guard against an accidental drop from _INITIAL_PROTECTED_ROUTES."""
    registered = set(protected_routes())
    required = {
        ("POST", "/api/commitments"),
        ("POST", "/api/saved-memories"),
        ("POST", "/api/projects"),
        ("POST", "/api/goals"),
        ("POST", "/api/decisions"),
        ("POST", "/api/habits"),
        ("POST", "/api/notes"),
        ("POST", "/api/content-assets"),
    }
    missing = required - registered
    assert not missing, f"missing from idempotency registry: {missing}"


def test_mark_idempotent_is_case_insensitive_on_method():
    """Registration + lookup must not care about header casing."""
    path = "/api/__unit_test_route__"
    mark_idempotent("post", path)
    assert is_protected("POST", path)
    assert is_protected("post", path)


def test_constants_have_sane_defaults():
    """Surface the HTTP idempotency defaults so a rogue change is visible."""
    assert IDEMPOTENCY_HEADER == "Idempotency-Key"
    assert MAX_FINGERPRINT_BYTES == 1 * 1024 * 1024
    assert MAX_KEY_LENGTH == 255


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/commitments"),
        ("POST", "/api/projects"),
        ("POST", "/api/notes"),
    ],
)
def test_is_protected_returns_true_for_known_entries(method: str, path: str):
    assert is_protected(method, path)


def test_is_protected_returns_false_for_unregistered_route():
    assert not is_protected("POST", "/api/__not_registered__")
    assert not is_protected("GET", "/api/commitments")


# ---------------------------------------------------------------------------
# Middleware-level unit tests (no DB container).
#
# These use a lightweight FastAPI app plus a mocked session factory so the
# full request → middleware → handler path is exercised without Docker. They
# cover the four critical decision paths: missing header, missing DB, route
# not registered, and 413 for oversized bodies.
# ---------------------------------------------------------------------------


@pytest.fixture
def ephemeral_app() -> FastAPI:
    """Build a minimal app with the middleware and one protected route."""
    mark_idempotent("POST", "/api/__test_idempotent__")

    app = FastAPI()
    app.add_middleware(IdempotencyMiddleware)

    @app.post("/api/__test_idempotent__")
    async def endpoint(body: dict):
        return {"echoed": body}

    @app.post("/api/__test_unprotected__")
    async def unprotected(body: dict):
        return {"echoed": body}

    return app


async def test_middleware_returns_400_when_header_missing(ephemeral_app):
    async with AsyncClient(
        transport=ASGITransport(app=ephemeral_app), base_url="http://t"
    ) as client:
        response = await client.post("/api/__test_idempotent__", json={"a": 1})
    assert response.status_code == 400
    assert response.json()["error"] == "idempotency_key_required"


async def test_middleware_returns_503_when_session_factory_missing(ephemeral_app):
    with patch("src.app.api.idempotency._session_factory", return_value=None):
        async with AsyncClient(
            transport=ASGITransport(app=ephemeral_app), base_url="http://t"
        ) as client:
            response = await client.post(
                "/api/__test_idempotent__",
                json={"a": 1},
                headers={"Idempotency-Key": "abc-123"},
            )
    assert response.status_code == 503
    assert response.json()["error"] == "database_error"


async def test_middleware_passes_through_unregistered_routes(ephemeral_app):
    async with AsyncClient(
        transport=ASGITransport(app=ephemeral_app), base_url="http://t"
    ) as client:
        response = await client.post("/api/__test_unprotected__", json={"a": 1})
    assert response.status_code == 200
    assert response.json() == {"echoed": {"a": 1}}


async def test_middleware_returns_413_on_oversized_body(ephemeral_app):
    # Build an oversized JSON payload just above the 1 MiB limit.
    big = "x" * (MAX_FINGERPRINT_BYTES + 10)
    async with AsyncClient(
        transport=ASGITransport(app=ephemeral_app), base_url="http://t"
    ) as client:
        response = await client.post(
            "/api/__test_idempotent__",
            json={"payload": big},
            headers={"Idempotency-Key": "big-one"},
        )
    assert response.status_code == 413
    assert response.json()["error"] == "payload_too_large"


async def test_middleware_returns_400_when_key_too_long(ephemeral_app):
    async with AsyncClient(
        transport=ASGITransport(app=ephemeral_app), base_url="http://t"
    ) as client:
        response = await client.post(
            "/api/__test_idempotent__",
            json={"a": 1},
            headers={"Idempotency-Key": "x" * (MAX_KEY_LENGTH + 1)},
        )
    assert response.status_code == 400
    assert response.json()["error"] == "idempotency_key_invalid"


async def test_middleware_caches_and_replays_response(ephemeral_app):
    """Full cache-hit flow with a fake session factory backed by an in-memory store."""
    store: dict[str, MagicMock] = {}

    async def fake_get_key(_session, *, key, **_kwargs):
        return store.get(key)

    async def fake_insert_started(
        _session,
        *,
        key,
        request_fingerprint,
        method,
        route,
    ):
        row = MagicMock()
        row.key = key
        row.request_fingerprint = request_fingerprint
        row.recovery_point = "started"
        row.method = method
        row.route = route
        row.response_status = None
        row.response_body = None
        row.response_headers = None
        from datetime import UTC, datetime, timedelta

        row.created_at = datetime.now(UTC)
        row.expires_at = row.created_at + timedelta(hours=24)
        store[key] = row
        return row

    async def fake_mark_completed(
        _session,
        *,
        key,
        response_status,
        response_body,
        response_headers=None,
    ):
        row = store.get(key)
        if row is None:
            return None
        row.recovery_point = "completed"
        row.response_status = response_status
        # Mirror the repo's _as_json_safe behaviour — bytes → parsed JSON.
        import json as _json

        if isinstance(response_body, bytes | bytearray):
            try:
                response_body = _json.loads(bytes(response_body).decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                response_body = {"__raw__": bytes(response_body).decode("utf-8", errors="replace")}
        row.response_body = response_body
        row.response_headers = dict(response_headers) if response_headers else None
        return row

    async def fake_mark_failed(_session, *, key):
        row = store.get(key)
        if row is None:
            return None
        row.recovery_point = "failed"
        return row

    # Fake async context-manager session factory that yields an AsyncMock
    # session. commit/rollback/flush/add are all no-ops here because the
    # repository functions themselves are monkeypatched.
    class _FakeSession:
        def __init__(self):
            self.flush = AsyncMock()
            self.commit = AsyncMock()
            self.rollback = AsyncMock()
            self.add = MagicMock()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    def fake_factory():
        return _FakeSession()

    with (
        patch(
            "src.app.api.idempotency._session_factory",
            return_value=fake_factory,
        ),
        patch(
            "src.app.persistence.repositories.idempotency.get_key",
            new=fake_get_key,
        ),
        patch(
            "src.app.persistence.repositories.idempotency.insert_started",
            new=fake_insert_started,
        ),
        patch(
            "src.app.persistence.repositories.idempotency.mark_completed",
            new=fake_mark_completed,
        ),
        patch(
            "src.app.persistence.repositories.idempotency.mark_failed",
            new=fake_mark_failed,
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=ephemeral_app), base_url="http://t"
        ) as client:
            first = await client.post(
                "/api/__test_idempotent__",
                json={"a": 1},
                headers={"Idempotency-Key": "replay-key"},
            )
            second = await client.post(
                "/api/__test_idempotent__",
                json={"a": 1},
                headers={"Idempotency-Key": "replay-key"},
            )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert second.headers.get("idempotent-replay") == "true"


async def test_middleware_returns_409_on_fingerprint_mismatch(ephemeral_app):
    """Same key + different body should fail with 409."""
    store: dict[str, MagicMock] = {}

    async def fake_get_key(_session, *, key, **_kwargs):
        return store.get(key)

    async def fake_insert_started(_session, *, key, request_fingerprint, method, route):
        row = MagicMock()
        row.key = key
        row.request_fingerprint = request_fingerprint
        row.recovery_point = "started"
        row.response_status = None
        row.response_body = None
        row.response_headers = None
        from datetime import UTC, datetime, timedelta

        row.created_at = datetime.now(UTC)
        row.expires_at = row.created_at + timedelta(hours=24)
        store[key] = row
        return row

    async def fake_mark_completed(
        _session, *, key, response_status, response_body, response_headers=None
    ):
        row = store.get(key)
        if row is not None:
            row.recovery_point = "completed"
            row.response_status = response_status
            row.response_body = response_body
        return row

    class _FakeSession:
        def __init__(self):
            self.flush = AsyncMock()
            self.commit = AsyncMock()
            self.rollback = AsyncMock()
            self.add = MagicMock()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    def fake_factory():
        return _FakeSession()

    with (
        patch(
            "src.app.api.idempotency._session_factory",
            return_value=fake_factory,
        ),
        patch(
            "src.app.persistence.repositories.idempotency.get_key",
            new=fake_get_key,
        ),
        patch(
            "src.app.persistence.repositories.idempotency.insert_started",
            new=fake_insert_started,
        ),
        patch(
            "src.app.persistence.repositories.idempotency.mark_completed",
            new=fake_mark_completed,
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=ephemeral_app), base_url="http://t"
        ) as client:
            first = await client.post(
                "/api/__test_idempotent__",
                json={"a": 1},
                headers={"Idempotency-Key": "dup-key"},
            )
            conflict = await client.post(
                "/api/__test_idempotent__",
                json={"a": 2},
                headers={"Idempotency-Key": "dup-key"},
            )

    assert first.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["error"] == "idempotency_key_conflict"

"""HTTP idempotency layer for mutating POST routes.

Clients send an ``Idempotency-Key`` header on any POST that creates state.
Semantics follow the current IETF draft
``draft-ietf-httpapi-idempotency-key-header``:

* Same key + same request body → the cached 2xx/4xx response is returned and
  the handler is NOT re-executed.
* Same key + different request body → ``409 Conflict``. The server refuses to
  re-use a key with a payload it did not originally see.
* Same key + in-flight (recovery_point="started") →
  ``409 Conflict`` with a "duplicate in-flight request" message.
* Different key → regular execution, fresh row inserted.
* Expired row → treated as absent; handler runs again.

Every completed HTTP response, including a 5xx response, is cached. This
preserves at-most-once execution when a downstream side effect succeeds but
the handler can only return an error. If the handler raises before producing a
response, the key remains in-flight and requires explicit operator recovery.

Max fingerprinted body size: 1 MiB (``413 Payload Too Large`` otherwise).
TTL: 24 hours (set via ``expires_at`` default in the migration).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from functools import lru_cache
from typing import Final

import structlog
from fastapi import FastAPI, Request
from sqlalchemy.exc import IntegrityError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response
from starlette.routing import compile_path
from starlette.types import Message

from src.app.persistence.database import get_engine
from src.app.persistence.repositories import idempotency as idempotency_repo

logger = structlog.get_logger()

IDEMPOTENCY_HEADER: Final = "Idempotency-Key"
"""Canonical header name — RFC-style title case, matched case-insensitively."""

MAX_FINGERPRINT_BYTES: Final = 1 * 1024 * 1024
"""Refuse to fingerprint bodies above 1 MiB with a 413."""

MAX_KEY_LENGTH: Final = 255
"""Upper bound on Idempotency-Key header value — matches table column width."""

# Mutable list to protect with idempotency. Populated by ``mark_idempotent``
# at import time of each route module so FastAPI's router traversal isn't
# needed. Keys are ``(METHOD, path)`` tuples; path is the raw route template
# passed to ``@router.post``.
_PROTECTED_ROUTES: Final[set[tuple[str, str]]] = set()


def mark_idempotent(method: str, path: str) -> None:
    """Register one route as requiring the Idempotency-Key header.

    Called once per protected endpoint at module import. The matcher compares
    against ``request.scope['route'].path`` at runtime so path parameters are
    honoured (e.g. ``/api/projects/{project_id}/epics``).
    """
    _PROTECTED_ROUTES.add((method.upper(), path))


def is_protected(method: str, path: str) -> bool:
    """Return True when ``(method, path)`` is registered for idempotency."""
    return (method.upper(), path) in _PROTECTED_ROUTES


def protected_routes() -> list[tuple[str, str]]:
    """Sorted snapshot of protected routes — used by tests and docs."""
    return sorted(_PROTECTED_ROUTES)


def _fingerprint(method: str, path: str, body: bytes) -> str:
    """Compute the canonical SHA-256 fingerprint for a request.

    We include method + path + body so a key cannot be reused across two
    endpoints or two verbs.
    """
    hasher = hashlib.sha256()
    hasher.update(method.upper().encode("ascii"))
    hasher.update(b"\x00")
    hasher.update(path.encode("utf-8"))
    hasher.update(b"\x00")
    hasher.update(body)
    return hasher.hexdigest()


def _error_response(
    *,
    status_code: int,
    error: str,
    message: str,
) -> JSONResponse:
    """Standardised error payload — mirrors ``ErrorResponse`` without import cycles."""
    return JSONResponse(
        status_code=status_code,
        content={"error": error, "message": message, "request_id": None},
    )


def _route_template(request: Request) -> str | None:
    """Extract the matched route template, not the raw URL path.

    ``BaseHTTPMiddleware`` runs *before* Starlette's routing resolves
    ``scope['route']``, so we cannot rely on the populated attribute. Instead
    we walk the FastAPI app's router ourselves and return the first route
    whose ``path_regex`` matches the URL path plus method — exactly how
    Starlette's router resolves it internally.
    """
    # Fast path: routing has already resolved (e.g. test clients that reuse a
    # request instance). Prefer the populated attribute when present.
    resolved = request.scope.get("route")
    if resolved is not None and hasattr(resolved, "path"):
        resolved_path = resolved.path
        if is_protected(request.method, resolved_path):
            return resolved_path

    path = request.url.path
    method = request.method.upper()
    # Match against our public registry instead of private FastAPI included-
    # router internals. Prefer the most specific template if paths overlap.
    candidates = sorted(
        (route_path for route_method, route_path in _PROTECTED_ROUTES if route_method == method),
        key=lambda candidate: (candidate.count("{"), -len(candidate)),
    )
    for route_path in candidates:
        if _compiled_path_regex(route_path).match(path) is not None:
            return route_path
    return None


@lru_cache(maxsize=512)
def _compiled_path_regex(path: str):
    return compile_path(path)[0]


async def _read_body(request: Request) -> bytes:
    """Buffer the request body so the handler can still read it later.

    Starlette's ``Request.body()`` caches the body on the request instance the
    first time it's awaited, so a second call (from the actual handler) is a
    cheap memory read rather than a re-read of the underlying stream.
    """
    return await request.body()


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Enforce Idempotency-Key semantics on registered mutating routes.

    The middleware runs *after* Starlette has matched the route (so
    ``scope['route']`` is populated) but before the handler, which is the
    default order for ``BaseHTTPMiddleware.dispatch``.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        # We only intercept POST requests to registered routes — everything
        # else is passed straight through.
        if request.method.upper() != "POST":
            return await call_next(request)

        # Starlette resolves the route template before this middleware runs,
        # so we can compare against ``mark_idempotent`` registrations.
        route_path = _route_template(request)
        if route_path is None or not is_protected(request.method, route_path):
            return await call_next(request)

        header_value = request.headers.get(IDEMPOTENCY_HEADER) or request.headers.get(
            IDEMPOTENCY_HEADER.lower()
        )
        if not header_value:
            return _error_response(
                status_code=400,
                error="idempotency_key_required",
                message=(f"{IDEMPOTENCY_HEADER} header is required for this endpoint."),
            )
        header_value = header_value.strip()
        if not header_value or len(header_value) > MAX_KEY_LENGTH:
            return _error_response(
                status_code=400,
                error="idempotency_key_invalid",
                message=(f"{IDEMPOTENCY_HEADER} must be 1-{MAX_KEY_LENGTH} characters."),
            )

        body = await _read_body(request)
        if len(body) > MAX_FINGERPRINT_BYTES:
            return _error_response(
                status_code=413,
                error="payload_too_large",
                message=(
                    f"Request body exceeds {MAX_FINGERPRINT_BYTES} bytes; cannot "
                    "fingerprint for idempotency."
                ),
            )

        fingerprint = _fingerprint(request.method, route_path, body)

        # Rehydrate the body so the downstream handler can still read it.
        # Starlette caches the body after one read, but we have to expose the
        # cached bytes via the ASGI receive callable — BaseHTTPMiddleware does
        # NOT reinject it for us.
        async def _receive() -> Message:
            return {
                "type": "http.request",
                "body": body,
                "more_body": False,
            }

        request._receive = _receive

        # Look up or create the idempotency record *before* running the
        # handler. This gives us the four semantics (hit / conflict / started
        # / miss) from a single code path.
        session_factory = _session_factory()
        if session_factory is None:
            # Database not initialised — fail closed. Without the DB we cannot
            # uphold the idempotency contract, so surface a clear 503.
            return _error_response(
                status_code=503,
                error="database_error",
                message=("Idempotency store is unavailable; please retry shortly."),
            )

        decision = await _resolve_idempotency(
            session_factory=session_factory,
            key=header_value,
            fingerprint=fingerprint,
            method=request.method,
            route=route_path,
        )
        if isinstance(decision, Response):
            return decision

        # Cache miss: run the handler and persist its response.
        response = await call_next(request)

        # Stream responses have to be materialised before we can cache them.
        response_body = await _materialise_response_body(response)

        try:
            async with session_factory() as session:
                await idempotency_repo.mark_completed(
                    session,
                    key=header_value,
                    response_status=response.status_code,
                    response_body=response_body,
                    response_headers=_cachable_headers(response),
                )
                await session.commit()
        except Exception:
            logger.warning(
                "idempotency_mark_completed_error",
                exc_info=True,
                key=header_value,
                status=response.status_code,
            )

        return _rebuild_response(response, response_body)


async def _resolve_idempotency(
    *,
    session_factory,
    key: str,
    fingerprint: str,
    method: str,
    route: str,
) -> Response | None:
    """Check for a prior attempt and return a replay / conflict response if so.

    Returns ``None`` when the caller should proceed with the handler (i.e. the
    row was freshly inserted as ``started``).
    """
    async with session_factory() as session:
        existing = await idempotency_repo.get_key(
            session,
            key=key,
            for_update=True,
        )
        if existing is not None:
            now = datetime.now(UTC)
            # Never infer that a running operation is abandoned from elapsed
            # wall time. Connector/LLM calls can legitimately be slow, and
            # retrying them would duplicate external side effects.
            if existing.recovery_point == "started":
                if existing.request_fingerprint != fingerprint:
                    return _error_response(
                        status_code=409,
                        error="idempotency_key_conflict",
                        message=(f"{IDEMPOTENCY_HEADER} was reused with a different payload."),
                    )
                logger.info(
                    "idempotency_in_flight_duplicate",
                    key=key,
                    route=route,
                    age_seconds=(now - existing.created_at).total_seconds(),
                )
                return _error_response(
                    status_code=409,
                    error="idempotency_in_flight",
                    message=(
                        "A request with this Idempotency-Key is still in flight. "
                        "Use a new key only after confirming the first operation did not complete."
                    ),
                )
            if existing.expires_at <= now:
                await idempotency_repo.reset_started(
                    session,
                    record=existing,
                    request_fingerprint=fingerprint,
                    method=method,
                    route=route,
                )
                await session.commit()
                return None
            if existing.request_fingerprint != fingerprint:
                logger.info(
                    "idempotency_fingerprint_mismatch",
                    key=key,
                    route=route,
                )
                return _error_response(
                    status_code=409,
                    error="idempotency_key_conflict",
                    message=(f"{IDEMPOTENCY_HEADER} was reused with a different payload."),
                )
            if existing.recovery_point == "completed":
                logger.info(
                    "idempotency_cache_hit",
                    key=key,
                    route=route,
                    status=existing.response_status,
                )
                return _replay_response(existing)
            # A legacy failed attempt reuses the unique row. Started attempts
            # are deliberately never reset automatically.
            await idempotency_repo.reset_started(
                session,
                record=existing,
                request_fingerprint=fingerprint,
                method=method,
                route=route,
            )
            await session.commit()
            return None

        # Fresh insert — capture started state.
        try:
            await idempotency_repo.insert_started(
                session,
                key=key,
                request_fingerprint=fingerprint,
                method=method,
                route=route,
            )
            await session.commit()
        except IntegrityError:
            # A concurrent request won the insert race. Re-read the row —
            # same-fingerprint wins fall through to in-flight handling.
            await session.rollback()
            existing = await idempotency_repo.get_active_key(session, key=key)
            if existing is None:
                logger.warning(
                    "idempotency_race_missing_row",
                    key=key,
                    route=route,
                )
                return _error_response(
                    status_code=409,
                    error="idempotency_in_flight",
                    message=(
                        "A concurrent request is processing this Idempotency-Key; retry shortly."
                    ),
                )
            if existing.request_fingerprint != fingerprint:
                return _error_response(
                    status_code=409,
                    error="idempotency_key_conflict",
                    message=(f"{IDEMPOTENCY_HEADER} was reused with a different payload."),
                )
            return _error_response(
                status_code=409,
                error="idempotency_in_flight",
                message=("A request with this Idempotency-Key is still in flight; retry shortly."),
            )
    return None


async def _materialise_response_body(response: Response) -> bytes:
    """Drain a streaming response so we can both cache and forward it.

    ``BaseHTTPMiddleware`` returns ``_StreamingResponse`` objects whose body is
    exposed via ``body_iterator``; we concatenate those chunks, cache them,
    and then hand a fresh ``Response`` back down the stack.
    """
    chunks: list[bytes] = []
    if hasattr(response, "body_iterator"):
        async for chunk in response.body_iterator:
            if isinstance(chunk, str):
                chunks.append(chunk.encode("utf-8"))
            else:
                chunks.append(bytes(chunk))
        return b"".join(chunks)
    # Plain Response already has a ``body`` attribute
    return bytes(response.body or b"")


def _rebuild_response(response: Response, body: bytes) -> Response:
    """Reconstruct a Response with the drained body plus the original metadata."""
    headers = dict(response.headers)
    # Content-length must reflect the materialised body length, not the
    # streamed marker.
    headers.pop("content-length", None)
    return Response(
        content=body,
        status_code=response.status_code,
        headers=headers,
        media_type=response.media_type,
    )


def _cachable_headers(response: Response) -> dict[str, str]:
    """Strip hop-by-hop and per-connection headers before caching."""
    blocked = {"content-length", "connection", "transfer-encoding", "date"}
    return {key: value for key, value in response.headers.items() if key.lower() not in blocked}


def _replay_response(row) -> Response:
    """Rehydrate a cached response from the row into a fresh Starlette Response."""
    body = row.response_body
    if body is None:
        content: bytes = b""
        media_type: str | None = None
    elif isinstance(body, dict | list | int | float | bool):
        content = json.dumps(body).encode("utf-8")
        media_type = "application/json"
    elif isinstance(body, str):
        content = body.encode("utf-8")
        media_type = "text/plain"
    else:
        content = json.dumps(body).encode("utf-8")
        media_type = "application/json"

    headers = dict(row.response_headers or {})
    headers["Idempotent-Replay"] = "true"
    return Response(
        content=content,
        status_code=row.response_status or 200,
        headers=headers,
        media_type=media_type,
    )


def _session_factory():
    """Resolve the async session factory, returning ``None`` if unavailable."""
    try:
        from src.app.persistence.database import _session_factory as sf

        return sf
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Central registration list — single source of truth for which routes require
# the Idempotency-Key header. Each entry is ``("POST", "<full-path-template>")``
# and must match the path Starlette matches at runtime (including the ``/api``
# prefix added by ``app.include_router``).
#
# Grouped for readability; the full list is exported via ``protected_routes()``
# and rendered into ``docs/api.md`` so clients can discover it.
# ---------------------------------------------------------------------------

_INITIAL_PROTECTED_ROUTES: Final[tuple[tuple[str, str], ...]] = (
    # --- Core state-creating endpoints ---
    ("POST", "/api/commitments"),
    ("POST", "/api/saved-memories"),
    ("POST", "/api/saved-memories/merge"),
    ("POST", "/api/projects"),
    ("POST", "/api/projects/{project_id}/epics"),
    ("POST", "/api/epics/{epic_id}/milestones"),
    ("POST", "/api/project-drafts/{draft_id}/apply"),
    ("POST", "/api/goals"),
    ("POST", "/api/decisions"),
    ("POST", "/api/habits"),
    ("POST", "/api/habits/{habit_id}/complete"),
    ("POST", "/api/notes"),
    ("POST", "/api/notes/daily/{note_date}"),
    ("POST", "/api/notes/{note_id}/links"),
    ("POST", "/api/note-canvases"),
    ("POST", "/api/content-assets"),
    ("POST", "/api/content-assets/{asset_id}/source-pack"),
    ("POST", "/api/scheduled-actions"),
    ("POST", "/api/scheduled-actions/{action_id}/run"),
    ("POST", "/api/contacts"),
    ("POST", "/api/contacts/{contact_id}/interactions"),
    ("POST", "/api/connectors/accounts"),
    ("POST", "/api/connectors/accounts/{account_id}/sync"),
    ("POST", "/api/reviews/generate"),
)


def _register_initial_routes() -> None:
    for method, path in _INITIAL_PROTECTED_ROUTES:
        mark_idempotent(method, path)


# Register on module import so the middleware sees them immediately.
_register_initial_routes()


def register_idempotent_routes(app: FastAPI) -> None:
    """Expose the protected-route list on ``app.state`` for observability/tests."""
    import contextlib

    app.state.idempotent_routes = protected_routes()
    # Engine may not be initialised yet at import time; accessing it here would
    # crash. We only need the side effect of populating app.state.
    with contextlib.suppress(RuntimeError):
        get_engine()

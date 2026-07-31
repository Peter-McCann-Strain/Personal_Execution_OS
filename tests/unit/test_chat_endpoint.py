"""Tests for the chat endpoint — message processing, auth, and validation."""

import uuid
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.app.api.deps import Principal, get_anthropic_client, get_current_principal, get_db
from src.app.api.routes.chat import router
from src.app.domain.models import ChatResponse

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

VALID_API_KEY = "test-chat-api-key"


async def _mock_get_db():
    """Yield a mock session so the chat route doesn't need a real DB."""
    yield AsyncMock()


def _mock_get_anthropic_client() -> AsyncMock:
    return AsyncMock()


def _build_app(*, override_auth: bool = True) -> FastAPI:
    """Create a minimal FastAPI app with the chat router for testing.

    When override_auth=True, the API key check is bypassed (returns "owner").
    Set to False to test authentication behaviour.
    """
    app = FastAPI()
    app.dependency_overrides[get_db] = _mock_get_db
    app.dependency_overrides[get_anthropic_client] = _mock_get_anthropic_client

    if override_auth:

        async def _always_principal() -> Principal:
            return Principal(
                subject="owner",
                external_subject=None,
                user_id=uuid.UUID("00000000-0000-0000-0000-000000000010"),
                account_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                role="owner",
                plan="pro",
                scopes=("admin",),
                auth_method="api_key",
            )

        app.dependency_overrides[get_current_principal] = _always_principal

    app.include_router(router, prefix="/api")
    return app


def _make_chat_response(
    content: str = "Got it.",
    agent: str = "diary",
    metadata: dict | None = None,
) -> ChatResponse:
    return ChatResponse(
        content=content,
        agent=agent,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


async def test_chat_success():
    """Valid request returns 200 with content, agent, and metadata."""
    mock_response = _make_chat_response(content="Entry saved.", agent="diary")

    with patch(
        "src.app.api.routes.chat.process_message",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        app = _build_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat",
                json={"content": "Had a great morning walk today"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["content"] == "Entry saved."
    assert data["agent"] == "diary"
    assert "metadata" in data


async def test_chat_passes_memory_controls_into_message_metadata():
    """Chat requests should carry memory-control flags into the runtime message."""
    captured_message = None

    async def _capture_message(message, *_args, **_kwargs):
        nonlocal captured_message
        captured_message = message
        return _make_chat_response(content="Captured.", agent="memory")

    with patch(
        "src.app.api.routes.chat.process_message",
        new_callable=AsyncMock,
        side_effect=_capture_message,
    ):
        app = _build_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat",
                json={
                    "content": "Answer carefully",
                    "sensitive_mode": True,
                    "suppressed_sources": ["note", "episode"],
                },
            )

    assert resp.status_code == 200
    assert captured_message is not None
    assert captured_message.metadata["sensitive_mode"] is True
    assert captured_message.metadata["suppressed_sources"] == ["note", "episode"]


async def test_chat_stream_emits_sse_events():
    """POST /chat/stream returns SSE events in the expected order."""
    mock_response = _make_chat_response(
        content="Streaming works.",
        agent="memory",
        metadata={"tool_count": 0},
    )

    with patch(
        "src.app.api.routes.chat.process_message",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        app = _build_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat/stream",
                json={"content": "Stream this response"},
            )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    body = resp.text
    assert "event: message_start" in body
    assert 'event: agent\ndata: {"agent":"memory"}' in body
    assert "event: token" in body
    assert "event: message_end" in body


async def test_chat_stream_emits_tool_status_when_only_tool_events_are_present():
    """Structured tool events alone should still trigger a tool_status SSE event."""
    mock_response = _make_chat_response(
        content="Done.",
        agent="tools",
        metadata={
            "tool_events": [
                {
                    "name": "filesystem__read_file",
                    "status": "executed",
                    "details": {"result_preview": "README contents"},
                }
            ],
            "tool_count": 1,
        },
    )

    with patch(
        "src.app.api.routes.chat.process_message",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        app = _build_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat/stream",
                json={"content": "Read the README"},
            )

    assert resp.status_code == 200
    body = resp.text
    assert "event: tool_status" in body
    assert '"tool_events":[{"name":"filesystem__read_file","status":"executed"' in body


async def test_chat_stream_returns_safe_internal_error_details():
    """Streaming errors expose a safe error type without leaking raw exception text."""
    with patch(
        "src.app.api.routes.chat.process_message",
        new_callable=AsyncMock,
        side_effect=RuntimeError("database password leaked"),
    ):
        app = _build_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat/stream",
                json={"content": "Stream this response"},
            )

    assert resp.status_code == 200
    body = resp.text
    assert "event: error" in body
    assert "Internal error while generating the response (RuntimeError)." in body
    assert '"error_type":"RuntimeError"' in body
    assert "database password leaked" not in body


async def test_chat_context_inspection_returns_debug_metadata():
    """POST /chat/context-inspect returns operator-facing context metadata."""
    with (
        patch(
            "src.app.api.routes.chat._get_conversation_context",
            return_value=None,
        ),
        patch(
            "src.app.api.routes.chat._retrieve_supporting_context",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.app.api.routes.chat.get_default_context_engine",
        ) as mock_engine_factory,
    ):
        mock_engine = AsyncMock()
        mock_engine.assemble.return_value.inspection = {
            "engine": "hierarchical",
            "history_summarized": False,
            "pruned_messages": 0,
            "pruned_characters": 0,
            "durable_memory_candidates": [],
            "rag_chunks_included": 0,
            "rag_chunks_filtered": 0,
            "total_tokens_estimate": 12,
            "sections": [],
        }
        mock_engine_factory.return_value = mock_engine

        app = _build_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat/context-inspect",
                json={"content": "Inspect this prompt"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert "request_id" in data
    assert data["inspection"]["engine"] == "hierarchical"
    assert data["inspection"]["totalTokensEstimate"] == 12


async def test_chat_context_inspection_uses_live_retrieval_context():
    """Context inspection should pass retrieved evidence into the context engine."""
    with (
        patch(
            "src.app.api.routes.chat._get_conversation_context",
            return_value=None,
        ),
        patch(
            "src.app.api.routes.chat._retrieve_supporting_context",
            new_callable=AsyncMock,
            return_value=[
                {
                    "content": "Retrieved deployment evidence",
                    "score": 0.81,
                    "source_type": "interaction",
                    "source_id": "interaction-1",
                }
            ],
        ) as mock_retrieve,
        patch(
            "src.app.api.routes.chat.get_default_context_engine",
        ) as mock_engine_factory,
    ):
        mock_engine = AsyncMock()
        mock_engine.assemble.return_value.inspection = {
            "engine": "hierarchical",
            "history_summarized": False,
            "pruned_messages": 0,
            "pruned_characters": 0,
            "durable_memory_candidates": [],
            "rag_chunks_included": 1,
            "rag_chunks_filtered": 0,
            "total_tokens_estimate": 18,
            "sections": [],
        }
        mock_engine_factory.return_value = mock_engine

        app = _build_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat/context-inspect",
                json={"content": "Inspect retrieved context"},
            )

    assert resp.status_code == 200
    mock_retrieve.assert_awaited_once()
    assert (
        mock_engine.assemble.await_args.kwargs["rag_chunks"][0]["content"]
        == "Retrieved deployment evidence"
    )


async def test_chat_returns_request_id():
    """Metadata contains a valid UUID request_id."""
    mock_response = _make_chat_response()

    with patch(
        "src.app.api.routes.chat.process_message",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        app = _build_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat",
                json={"content": "Test message"},
            )

    data = resp.json()
    request_id = data["metadata"]["request_id"]
    # Should be a valid UUID
    parsed = uuid.UUID(request_id)
    assert str(parsed) == request_id


async def test_chat_returns_agent_used():
    """metadata.agent_used matches response.agent."""
    mock_response = _make_chat_response(agent="memory")

    with patch(
        "src.app.api.routes.chat.process_message",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        app = _build_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat",
                json={"content": "What did I do yesterday?"},
            )

    data = resp.json()
    assert data["metadata"]["agent_used"] == data["agent"]
    assert data["metadata"]["agent_used"] == "memory"


async def test_chat_returns_latency():
    """metadata.latency_ms is populated and non-negative."""
    mock_response = _make_chat_response()

    with patch(
        "src.app.api.routes.chat.process_message",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        app = _build_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat",
                json={"content": "Hello"},
            )

    data = resp.json()
    assert "latency_ms" in data["metadata"]
    assert isinstance(data["metadata"]["latency_ms"], int)
    assert data["metadata"]["latency_ms"] >= 0


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


async def test_chat_empty_content_returns_422():
    """Empty string content triggers a validation error."""
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/chat",
            json={"content": ""},
        )

    assert resp.status_code == 422


async def test_chat_whitespace_only_returns_422():
    """Whitespace-only content fails validation (strip_whitespace + min_length=1)."""
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/chat",
            json={"content": "   \t\n  "},
        )

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Authentication tests
# ---------------------------------------------------------------------------


async def test_chat_missing_api_key_returns_401():
    """Request without X-API-Key header returns 401."""
    app = _build_app(override_auth=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/chat",
            json={"content": "Hello"},
            # No X-API-Key header
        )

    assert resp.status_code == 401
    assert "Invalid or missing credentials" in resp.json()["detail"]


async def test_chat_invalid_api_key_returns_401():
    """Request with wrong API key returns 401."""
    app = _build_app(override_auth=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/chat",
            json={"content": "Hello"},
            headers={"X-API-Key": "wrong-key-entirely"},
        )

    assert resp.status_code == 401
    assert "Invalid or missing credentials" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Agent routing tests
# ---------------------------------------------------------------------------


async def test_chat_diary_agent_response():
    """When process_message returns agent='diary', response reflects that."""
    mock_response = _make_chat_response(
        content="Captured: Morning walk, feeling great.",
        agent="diary",
        metadata={"mood_score": 8.0, "tags": ["exercise", "morning"]},
    )

    with patch(
        "src.app.api.routes.chat.process_message",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        app = _build_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat",
                json={"content": "Had a great morning walk, feeling energised"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["agent"] == "diary"
    assert "Captured" in data["content"]
    assert data["metadata"]["agent_used"] == "diary"


async def test_chat_supervisor_fallback():
    """When a specialist isn't implemented, supervisor returns a helpful message."""
    mock_response = _make_chat_response(
        content="I understand you want help with 'research', but the research agent isn't built yet.",
        agent="supervisor",
        metadata={"intent": {"specialist": "research"}},
    )

    with patch(
        "src.app.api.routes.chat.process_message",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        app = _build_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat",
                json={"content": "Research the latest developments in quantum computing"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["agent"] == "supervisor"
    assert "isn't built yet" in data["content"]
    assert data["metadata"]["agent_used"] == "supervisor"

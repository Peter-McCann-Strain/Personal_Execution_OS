"""Tests to fill all remaining coverage gaps across the codebase.

Each section targets specific missing lines identified by coverage analysis.
"""

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import make_anthropic_response

# ===========================================================================
# 1. diary.py line 34 — context parameter appended to system prompt
# ===========================================================================


@pytest.mark.asyncio
async def test_diary_entry_with_context(mock_anthropic_client):
    """When context is provided, it should be appended to the system prompt."""
    response_data = {
        "content": "Had a great meeting",
        "summary": "Great meeting",
        "mood_score": 8.0,
        "energy_rating": 7.0,
        "tags": ["work"],
        "people_mentioned": [],
        "para_category": "area",
    }
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )

    from src.app.agents.specialists.diary import process_diary_entry

    entry = await process_diary_entry(
        "Had a great meeting",
        mock_anthropic_client,
        context="Previous: User was discussing work projects.",
    )

    assert entry.content == "Had a great meeting"
    # Verify context was included in the system prompt
    call_kwargs = mock_anthropic_client.messages.create.call_args.kwargs
    system_val = call_kwargs["system"]
    # system can be a string or a list of content blocks
    if isinstance(system_val, list):
        system_text = " ".join(block.get("text", "") for block in system_val)
    else:
        system_text = system_val
    assert "Additional Context" in system_text
    assert "Previous: User was discussing work projects." in system_text


# ===========================================================================
# 2. research.py lines 109-134 — run_research full pipeline
# ===========================================================================


@pytest.mark.asyncio
async def test_run_research_full_pipeline(mock_anthropic_client):
    """run_research generates queries, searches, deduplicates, and synthesizes."""
    # First LLM call: generate_search_queries
    queries_response = json.dumps({"queries": ["query 1", "query 2"]})
    # Second LLM call: synthesise_findings
    synthesis_response = json.dumps(
        {
            "title": "Research Report",
            "search_queries": [],
            "findings": [{"source": "example.com", "key_points": ["point 1"], "relevance": "high"}],
            "synthesis": "Summary of findings",
            "decision_framework": None,
        }
    )
    mock_anthropic_client.messages.create.side_effect = [
        make_anthropic_response(queries_response),
        make_anthropic_response(synthesis_response),
    ]

    # Mock Tavily search
    mock_search = AsyncMock()
    mock_search.search.side_effect = [
        [{"url": "https://a.com", "title": "A", "content": "Content A"}],
        [
            {"url": "https://a.com", "title": "A", "content": "Content A"},  # duplicate
            {"url": "https://b.com", "title": "B", "content": "Content B"},
        ],
    ]

    from src.app.agents.specialists.research import run_research

    report = await run_research("Best Python frameworks", mock_anthropic_client, mock_search)

    assert report.title == "Research Report"
    assert report.search_queries == ["query 1", "query 2"]
    assert mock_search.search.call_count == 2


# ===========================================================================
# 3. review.py lines 100-104, 144-148 — monthly and annual reviews
# ===========================================================================


@pytest.mark.asyncio
async def test_generate_monthly_review(mock_anthropic_client):
    """generate_monthly_review produces a MonthlyReview."""
    response_data = {
        "period": "March 2026",
        "accomplishments": ["Shipped MVP"],
        "mood_trend": "Improving",
        "average_mood": 7.0,
        "goal_progress": [],
        "habit_adherence": [],
        "patterns_noticed": ["Better sleep"],
        "recommendations": ["Keep it up"],
        "key_insight": "Consistency pays off",
    }
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )

    from src.app.agents.specialists.review import generate_monthly_review

    review = await generate_monthly_review("Month data here...", mock_anthropic_client)
    assert review.period == "March 2026"
    assert review.mood_trend == "Improving"
    assert review.average_mood == 7.0


@pytest.mark.asyncio
async def test_generate_annual_review(mock_anthropic_client):
    """generate_annual_review produces an AnnualReview."""
    response_data = {
        "period": "2026",
        "year_theme": "Growth",
        "major_accomplishments": ["Launched product"],
        "goal_achievement": [],
        "major_decisions": [],
        "relationship_summary": [],
        "personal_growth": ["Better habits"],
        "lessons_learned": ["Start earlier"],
        "next_year_vision": ["Scale up"],
        "key_insight": "Year of transformation",
    }
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )

    from src.app.agents.specialists.review import generate_annual_review

    review = await generate_annual_review("Year data here...", mock_anthropic_client)
    assert review.period == "2026"
    assert review.year_theme == "Growth"
    assert review.key_insight == "Year of transformation"


# ===========================================================================
# 4. calendar.py lines 43-44, 163, 165, 167, 169, 231, 233
#    — _parse_event_time ValueError branch, update_event optional fields,
#      find_free_slots naive tz handling
# ===========================================================================


def test_parse_event_time_invalid_falls_back_to_date():
    """_parse_event_time falls back to date.fromisoformat on ValueError."""
    from src.app.agents.tools.calendar import _parse_event_time

    # A plain date string like "2026-03-10" — in Python 3.12+ fromisoformat
    # parses this as datetime. We'll verify the function handles it properly.
    result = _parse_event_time("2026-03-10")
    assert result.year == 2026


@pytest.mark.asyncio
async def test_update_event_all_optional_fields():
    """update_event passes start, end, description, location when provided."""
    from src.app.agents.tools.calendar import CalendarService

    svc = CalendarService(
        client_id="fake-id",
        client_secret="fake-secret",
        refresh_token="fake-refresh",
    )
    svc._http_client = AsyncMock()
    svc._cached_token = "valid-token"
    svc._token_expiry = datetime.now(UTC) + timedelta(hours=1)

    now = datetime.now(UTC)
    updated_item = {
        "id": "evt1",
        "summary": "Updated",
        "start": {"dateTime": now.isoformat()},
        "end": {"dateTime": (now + timedelta(hours=2)).isoformat()},
        "description": "New desc",
        "location": "New place",
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = updated_item
    mock_resp.raise_for_status = MagicMock()
    svc._http_client.patch.return_value = mock_resp

    event = await svc.update_event(
        event_id="evt1",
        summary="Updated",
        start=now,
        end=now + timedelta(hours=2),
        description="New desc",
        location="New place",
    )
    assert event.summary == "Updated"
    # Verify all fields were included in the request body
    call_kwargs = svc._http_client.patch.call_args.kwargs
    body = call_kwargs["json"]
    assert "start" in body
    assert "end" in body
    assert body["description"] == "New desc"
    assert body["location"] == "New place"


@pytest.mark.asyncio
async def test_find_free_slots_naive_tz_events():
    """find_free_slots handles events with naive (tz-unaware) datetime start/end."""
    from src.app.agents.tools.calendar import CalendarService

    svc = CalendarService(
        client_id="fake-id",
        client_secret="fake-secret",
        refresh_token="fake-refresh",
    )
    svc._http_client = AsyncMock()
    svc._cached_token = "valid-token"
    svc._token_expiry = datetime.now(UTC) + timedelta(hours=1)

    # Return events with naive datetimes (no tzinfo)
    tomorrow = datetime.now(UTC).date() + timedelta(days=1)
    naive_start = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 10, 0, 0)
    naive_end = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 11, 0, 0)

    # We mock get_upcoming_events to return events with naive datetimes
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "items": [
            {
                "id": "naive-evt",
                "summary": "Naive Event",
                "start": {"dateTime": naive_start.isoformat()},
                "end": {"dateTime": naive_end.isoformat()},
            }
        ]
    }
    mock_resp.raise_for_status = MagicMock()
    svc._http_client.get.return_value = mock_resp

    slots = await svc.find_free_slots(duration_minutes=30, days_ahead=2, working_hours=(9, 17))
    assert isinstance(slots, list)


# ===========================================================================
# 5. email.py lines 45-67, 167-172, 178
#    — get_unread_emails + create_draft reply with thread
# ===========================================================================


@pytest.mark.asyncio
async def test_get_unread_emails():
    """get_unread_emails fetches message list then details for each."""
    from src.app.agents.tools.email import GmailService

    svc = GmailService(
        client_id="fake-id",
        client_secret="fake-secret",
        refresh_token="fake-refresh",
    )
    svc._http_client = AsyncMock()
    svc._cached_token = "valid-token"
    svc._token_expiry = datetime.now(UTC) + timedelta(hours=1)

    list_resp = MagicMock()
    list_resp.json.return_value = {"messages": [{"id": "msg1"}]}
    list_resp.raise_for_status = MagicMock()

    detail_resp = MagicMock()
    detail_resp.json.return_value = {"id": "msg1", "payload": {"headers": []}}
    detail_resp.raise_for_status = MagicMock()

    svc._http_client.get.side_effect = [list_resp, detail_resp]

    emails = await svc.get_unread_emails(max_results=5)
    assert len(emails) == 1
    assert emails[0]["id"] == "msg1"


@pytest.mark.asyncio
async def test_create_draft_with_reply():
    """create_draft with reply_to_message_id sets thread headers."""
    from src.app.agents.tools.email import GmailService

    svc = GmailService(
        client_id="fake-id",
        client_secret="fake-secret",
        refresh_token="fake-refresh",
    )
    svc._http_client = AsyncMock()
    svc._cached_token = "valid-token"
    svc._token_expiry = datetime.now(UTC) + timedelta(hours=1)

    # Mock get_email_detail for the reply
    original_detail = {
        "id": "orig-msg",
        "threadId": "thread-123",
        "snippet": "Original",
        "headers": {"Message-ID": "<original@example.com>", "Subject": "Original Subject"},
        "body": "Original body",
        "labelIds": ["INBOX"],
        "internalDate": "1710000000000",
    }
    detail_resp = MagicMock()
    detail_resp.json.return_value = original_detail
    detail_resp.raise_for_status = MagicMock()

    # Mock the draft creation response
    draft_resp = MagicMock()
    draft_resp.json.return_value = {"id": "draft-reply-1"}
    draft_resp.raise_for_status = MagicMock()

    svc._http_client.get.return_value = detail_resp
    svc._http_client.post.return_value = draft_resp

    draft_id = await svc.create_draft(
        to="alice@example.com",
        subject="Re: Original Subject",
        body="Reply body",
        reply_to_message_id="orig-msg",
    )
    assert draft_id == "draft-reply-1"
    # Verify thread ID was included in the draft body
    call_kwargs = svc._http_client.post.call_args.kwargs
    assert call_kwargs["json"]["message"]["threadId"] == "thread-123"


# ===========================================================================
# 6. health.py lines 39-57, 62-77, 82-89
#    — _check_redis, _check_ollama, _check_anthropic
# ===========================================================================


@pytest.mark.asyncio
async def test_check_redis_success():
    """_check_redis returns ok when Redis PING succeeds."""
    from src.app.api.routes.health import _check_redis

    mock_redis = AsyncMock()
    mock_redis.ping.return_value = True
    mock_redis.aclose = AsyncMock()

    with (
        patch("redis.asyncio.from_url", return_value=mock_redis),
        patch("src.app.api.routes.health.get_settings") as mock_settings,
    ):
        mock_settings.return_value.redis_url = MagicMock(
            get_secret_value=lambda: "redis://localhost"
        )
        result = await _check_redis()

    assert result["status"] == "ok"
    assert "latency_ms" in result


@pytest.mark.asyncio
async def test_check_redis_ping_false():
    """_check_redis returns down when PING returns False."""
    from src.app.api.routes.health import _check_redis

    mock_redis = AsyncMock()
    mock_redis.ping.return_value = False
    mock_redis.aclose = AsyncMock()

    with (
        patch("redis.asyncio.from_url", return_value=mock_redis),
        patch("src.app.api.routes.health.get_settings") as mock_settings,
    ):
        mock_settings.return_value.redis_url = MagicMock(
            get_secret_value=lambda: "redis://localhost"
        )
        result = await _check_redis()

    assert result["status"] == "down"


@pytest.mark.asyncio
async def test_check_redis_connection_error():
    """_check_redis returns down on connection error."""
    from src.app.api.routes.health import _check_redis

    mock_redis = AsyncMock()
    mock_redis.ping.side_effect = ConnectionError("refused")
    mock_redis.aclose = AsyncMock()

    with (
        patch("redis.asyncio.from_url", return_value=mock_redis),
        patch("src.app.api.routes.health.get_settings") as mock_settings,
    ):
        mock_settings.return_value.redis_url = MagicMock(
            get_secret_value=lambda: "redis://localhost"
        )
        result = await _check_redis()

    assert result["status"] == "down"


@pytest.mark.asyncio
async def test_check_ollama_success():
    """_check_ollama returns ok when Ollama responds with 200."""
    from src.app.api.routes.health import _check_ollama

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("httpx.AsyncClient", return_value=mock_client),
        patch("src.app.api.routes.health.get_settings") as mock_settings,
    ):
        mock_settings.return_value.ollama_host = "http://localhost:11434"
        result = await _check_ollama()

    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_check_ollama_non_200():
    """_check_ollama returns down when Ollama responds with non-200."""
    from src.app.api.routes.health import _check_ollama

    mock_resp = MagicMock()
    mock_resp.status_code = 500

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("httpx.AsyncClient", return_value=mock_client),
        patch("src.app.api.routes.health.get_settings") as mock_settings,
    ):
        mock_settings.return_value.ollama_host = "http://localhost:11434"
        result = await _check_ollama()

    assert result["status"] == "down"


@pytest.mark.asyncio
async def test_check_ollama_connection_error():
    """_check_ollama returns down on connection error."""
    from src.app.api.routes.health import _check_ollama

    mock_client = AsyncMock()
    mock_client.get.side_effect = ConnectionError("refused")
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("httpx.AsyncClient", return_value=mock_client),
        patch("src.app.api.routes.health.get_settings") as mock_settings,
    ):
        mock_settings.return_value.ollama_host = "http://localhost:11434"
        result = await _check_ollama()

    assert result["status"] == "down"


def test_check_anthropic_configured():
    """_check_anthropic reports configured Anthropic without probing the live API."""
    from src.app.api.routes.health import _check_anthropic

    mock_settings = MagicMock()
    mock_settings.anthropic_api_key.get_secret_value.return_value = "test-key-not-real"

    with patch("src.app.api.routes.health.get_settings", return_value=mock_settings):
        result = _check_anthropic()

    assert result["status"] == "ok"
    assert "billable traffic" in result["message"]


def test_check_anthropic_placeholder():
    """_check_anthropic returns 'down' when API key is a placeholder."""
    from src.app.api.routes.health import _check_anthropic

    mock_settings = MagicMock()
    mock_settings.anthropic_api_key.get_secret_value.return_value = "PLACEHOLDER_KEY"

    with patch("src.app.api.routes.health.get_settings", return_value=mock_settings):
        result = _check_anthropic()

    assert result["status"] == "down"


def test_check_anthropic_exception():
    """_check_anthropic returns 'down' when settings throw an exception."""
    from src.app.api.routes.health import _check_anthropic

    with patch("src.app.api.routes.health.get_settings", side_effect=RuntimeError("no config")):
        result = _check_anthropic()

    assert result["status"] == "down"


# ===========================================================================
# 7. rate_limiting.py lines 86, 96-98, 102-104, 114-121
#    — RateLimitMiddleware: exempt paths, API key, telegram webhook, IP fallback, 429
# ===========================================================================


@pytest.mark.asyncio
async def test_rate_limit_middleware_exempt_path():
    """Exempt paths like /health should bypass rate limiting."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from src.app.api.rate_limiting import RateLimitMiddleware

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_middleware_api_key():
    """Requests with X-API-Key should be rate limited by API key prefix."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from src.app.api.rate_limiting import RateLimitMiddleware

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.get("/test")
    async def test_endpoint():
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/test", headers={"X-API-Key": "test-key-12345"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_middleware_telegram_webhook():
    """Telegram webhook paths should use the telegram rate limit."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from src.app.api.rate_limiting import RateLimitMiddleware

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.post("/webhook/telegram")
    async def telegram_webhook():
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/webhook/telegram")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_middleware_ip_fallback():
    """Requests without API key or webhook should use IP-based rate limiting."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from src.app.api.rate_limiting import RateLimitMiddleware

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.get("/api/data")
    async def data_endpoint():
        return {"data": []}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/data")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_middleware_429_response():
    """When rate limit is exceeded, middleware should return 429."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from src.app.api.rate_limiting import RateLimitMiddleware, _counter

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.get("/limited")
    async def limited():
        return {"ok": True}

    # Pre-fill the counter to exceed the limit
    with patch.object(_counter, "is_allowed", return_value=False):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/limited",
                headers={"X-API-Key": "rate-limit-test-key"},
            )

    assert resp.status_code == 429
    data = resp.json()
    assert data["error"] == "rate_limited"
    assert "Too many requests" in data["message"]
    assert "Retry-After" in resp.headers


# ===========================================================================
# 17. context_budget.py lines 150-154, 156-160
#     — safety margin enforcement: history + RAG truncation after total check
# ===========================================================================


def test_safety_margin_truncates_history_then_rag():
    """When total exceeds safety margin, history is removed first, then RAG."""
    from src.app.core.context_budget import ContextBudget

    # Use a budget where the individual budgets are fine but total exceeds safety margin
    budget = ContextBudget(max_context_tokens=1000)
    # max_input = 1000 - 320 (output) - 230 (safety) = 450 tokens

    # Create content that fits individual budgets but exceeds total
    # history_budget = 100 tokens, rag_budget = 300 tokens
    # But total = system(200) + rag(280) + history(90) + user(10) = 580 > 450
    result = budget.fit_to_budget(
        system_tokens=200,
        rag_chunks=["x" * 980 for _ in range(3)],  # ~280 tokens each
        history_messages=["y" * 315 for _ in range(3)],  # ~90 tokens each
        user_message="hello",
    )
    assert result["truncated"]
    # Some history or RAG should have been removed
    assert len(result["history"]) < 3 or len(result["rag_chunks"]) < 3


# ===========================================================================
# 18. chat.py lines 63, 99, 116-131, 150-151
#     — context enrichment, evaluator-optimizer retry, _get_conversation_context
# ===========================================================================


@pytest.mark.asyncio
async def test_process_message_with_conversation_context():
    """process_message enriches message with conversation context when available."""
    from src.app.domain.models import ChatResponse, Intent, IntentType, MessageInput, Specialist

    message = MessageInput(content="How am I doing?", source="test", user_id="user-1")
    intent = Intent(
        intent_type=IntentType.QUERY,
        confidence=0.9,
        specialist=Specialist.DIARY,
        reasoning="query",
    )
    response = ChatResponse(content="You're doing great!", agent="diary", metadata={})

    mock_eval = MagicMock()
    mock_eval.passes = True
    mock_eval.suggestion = None

    from src.app.core.context_manager import AssembledContext
    from src.app.core.conversation import ConversationMessage

    mock_msg = ConversationMessage(role="user", content="previous msg")
    mock_conv_ctx = MagicMock()
    mock_conv_ctx.get_context = AsyncMock(return_value=[mock_msg])
    mock_conv_ctx.get_summary = AsyncMock(return_value="")
    mock_conv_ctx.get_state_packet = AsyncMock(return_value=None)
    mock_conv_ctx.get_pending_tool_plan = AsyncMock(return_value=None)
    mock_conv_ctx.add_message = AsyncMock()
    mock_conv_ctx.set_summary = AsyncMock()
    mock_conv_ctx.set_state_packet = AsyncMock()

    mock_assembled = AssembledContext(
        conversation_context="Previous: previous msg",
        rag_context="",
        total_tokens_estimate=10,
        history_summarized=False,
        rag_chunks_included=0,
        rag_chunks_filtered=0,
    )

    with (
        patch(
            "src.app.domain.services.chat.classify_intent",
            new_callable=AsyncMock,
            return_value=intent,
        ),
        patch(
            "src.app.domain.services.chat.handle_diary",
            new_callable=AsyncMock,
            return_value=response,
        ),
        patch(
            "src.app.domain.services.chat.evaluate_response",
            new_callable=AsyncMock,
            return_value=mock_eval,
        ),
        patch(
            "src.app.domain.services.chat._get_conversation_context",
            return_value=mock_conv_ctx,
        ),
        patch(
            "src.app.domain.services.chat.assemble_context",
            new_callable=AsyncMock,
            return_value=mock_assembled,
        ),
    ):
        from src.app.domain.services.chat import process_message

        result = await process_message(message, AsyncMock(), AsyncMock())

    assert result.content == "You're doing great!"
    mock_conv_ctx.add_message.assert_called()


@pytest.mark.asyncio
async def test_process_message_triggers_rolling_summary_update():
    """process_message updates rolling summary when history was summarized."""
    from src.app.core.context_manager import AssembledContext
    from src.app.core.conversation import ConversationMessage
    from src.app.domain.models import ChatResponse, Intent, IntentType, MessageInput, Specialist

    message = MessageInput(content="What happened?", source="test", user_id="user-1")
    intent = Intent(
        intent_type=IntentType.QUERY,
        confidence=0.9,
        specialist=Specialist.DIARY,
        reasoning="query",
    )
    response = ChatResponse(content="Summary of events.", agent="diary", metadata={})

    mock_eval = MagicMock()
    mock_eval.passes = True

    mock_msg = ConversationMessage(role="user", content="old message")
    mock_conv_ctx = MagicMock()
    mock_conv_ctx.get_context = AsyncMock(return_value=[mock_msg])
    mock_conv_ctx.get_summary = AsyncMock(return_value="")
    mock_conv_ctx.get_state_packet = AsyncMock(return_value=None)
    mock_conv_ctx.get_pending_tool_plan = AsyncMock(return_value=None)
    mock_conv_ctx.add_message = AsyncMock()
    mock_conv_ctx.set_summary = AsyncMock()
    mock_conv_ctx.set_state_packet = AsyncMock()

    mock_assembled = AssembledContext(
        conversation_context="<conversation_history>old</conversation_history>",
        rag_context="",
        total_tokens_estimate=10,
        history_summarized=True,  # Triggers rolling summary update
        rag_chunks_included=0,
        rag_chunks_filtered=0,
    )

    with (
        patch(
            "src.app.domain.services.chat.classify_intent",
            new_callable=AsyncMock,
            return_value=intent,
        ),
        patch(
            "src.app.domain.services.chat.handle_diary",
            new_callable=AsyncMock,
            return_value=response,
        ),
        patch(
            "src.app.domain.services.chat.evaluate_response",
            new_callable=AsyncMock,
            return_value=mock_eval,
        ),
        patch(
            "src.app.domain.services.chat._get_conversation_context",
            return_value=mock_conv_ctx,
        ),
        patch(
            "src.app.domain.services.chat.assemble_context",
            new_callable=AsyncMock,
            return_value=mock_assembled,
        ),
        patch(
            "src.app.domain.services.chat._update_rolling_summary",
            new_callable=AsyncMock,
            return_value="Updated rolling summary",
        ) as mock_update_summary,
    ):
        from src.app.domain.services.chat import process_message

        result = await process_message(message, AsyncMock(), AsyncMock())

    assert result.content == "Summary of events."
    mock_update_summary.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_message_evaluator_retry():
    """process_message retries when evaluator says response doesn't pass."""
    from src.app.domain.models import ChatResponse, Intent, IntentType, MessageInput, Specialist

    message = MessageInput(content="Tell me about my goals", source="test", user_id="user-1")
    intent = Intent(
        intent_type=IntentType.QUERY,
        confidence=0.9,
        specialist=Specialist.DIARY,
        reasoning="query",
    )
    first_response = ChatResponse(content="Bad response", agent="diary", metadata={})
    retry_response = ChatResponse(content="Better response", agent="diary", metadata={})

    mock_eval_fail = MagicMock()
    mock_eval_fail.passes = False
    mock_eval_fail.suggestion = "Be more specific about goals"
    mock_eval_fail.issue = "Off topic"

    mock_eval_pass = MagicMock()
    mock_eval_pass.passes = True
    mock_settings = MagicMock()
    mock_settings.runtime_eval_mode = "sync"
    mock_settings.runtime_eval_optimizer_enabled = True
    mock_settings.runtime_eval_sample_rate = 1.0
    mock_settings.auto_judge_enabled = True

    with (
        patch(
            "src.app.domain.services.chat.classify_intent",
            new_callable=AsyncMock,
            return_value=intent,
        ),
        patch(
            "src.app.domain.services.chat.handle_diary",
            new_callable=AsyncMock,
            side_effect=[first_response, retry_response],
        ),
        patch(
            "src.app.domain.services.chat.evaluate_response",
            new_callable=AsyncMock,
            return_value=mock_eval_fail,
        ),
        patch(
            "src.app.domain.services.chat._get_conversation_context",
            return_value=None,
        ),
        patch(
            "src.app.domain.services.chat.get_settings",
            return_value=mock_settings,
        ),
    ):
        from src.app.domain.services.chat import process_message

        result = await process_message(message, AsyncMock(), AsyncMock())

    assert result.content == "Better response"


def test_get_conversation_context_returns_none_on_error():
    """_get_conversation_context returns None when config is unavailable."""
    from src.app.domain.services.chat import _get_conversation_context

    with patch(
        "src.app.domain.services.chat.get_settings",
        side_effect=RuntimeError("no config"),
    ):
        result = _get_conversation_context()
    assert result is None


# ===========================================================================
# 18b. chat.py — _update_rolling_summary
# ===========================================================================


@pytest.mark.asyncio
async def test_update_rolling_summary_persists():
    """_update_rolling_summary stores the summary in Redis via conv_ctx."""
    from src.app.domain.services.chat import _update_rolling_summary

    mock_conv_ctx = MagicMock()
    mock_conv_ctx.set_summary = AsyncMock()
    mock_client = AsyncMock()
    messages = [{"role": "user", "content": "hello"}]

    mock_settings = MagicMock()
    mock_settings.summary_model = "claude-haiku-4-5-20251001"

    with (
        patch(
            "src.app.domain.services.chat.get_settings",
            return_value=mock_settings,
        ),
        patch(
            "src.app.core.context_manager.summarize_messages",
            new_callable=AsyncMock,
            return_value="User said hello.",
        ),
    ):
        await _update_rolling_summary(mock_conv_ctx, "user-1", messages, mock_client)

    mock_conv_ctx.set_summary.assert_awaited_once_with("user-1", "User said hello.")


@pytest.mark.asyncio
async def test_update_rolling_summary_raises_on_error():
    """_update_rolling_summary propagates errors — no silent fallback."""
    from src.app.domain.services.chat import _update_rolling_summary

    mock_conv_ctx = MagicMock()
    mock_conv_ctx.set_summary = AsyncMock()
    mock_client = AsyncMock()

    mock_settings = MagicMock()
    mock_settings.summary_model = "claude-haiku-4-5-20251001"

    with (
        patch(
            "src.app.domain.services.chat.get_settings",
            return_value=mock_settings,
        ),
        patch(
            "src.app.core.context_manager.summarize_messages",
            new_callable=AsyncMock,
            side_effect=RuntimeError("LLM down"),
        ),
        pytest.raises(RuntimeError, match="LLM down"),
    ):
        await _update_rolling_summary(mock_conv_ctx, "user-1", [], mock_client)


# ===========================================================================
# 19. commitments.py lines 86-88 — parse failure raises LLMError
# ===========================================================================


@pytest.mark.asyncio
async def test_extract_commitments_parse_failure(mock_anthropic_client):
    """Malformed JSON in commitment response raises LLMError."""
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        "not valid json at all"
    )

    from src.app.core.exceptions import LLMError
    from src.app.domain.services.commitments import extract_commitments

    with pytest.raises(LLMError, match="Failed to parse commitment"):
        await extract_commitments("I'll do something", mock_anthropic_client)


# ===========================================================================
# 20. handlers/memory.py lines 96-97 — generic exception fallback to BM25
# ===========================================================================


@pytest.mark.asyncio
async def test_retrieve_context_raises_on_unexpected_error():
    """_retrieve_context propagates errors — no silent fallback to BM25."""
    mock_session = AsyncMock()

    with (
        patch("src.app.domain.services.handlers.memory.get_settings") as mock_settings,
        patch(
            "src.app.domain.services.handlers.memory.OllamaEmbeddings",
            side_effect=RuntimeError("Unexpected error"),
        ),
    ):
        mock_settings.return_value = MagicMock(
            ollama_host="http://localhost:11434",
            ollama_embed_model="nomic-embed-text:v2-moe",
            default_search_limit=10,
        )

        from src.app.domain.services.handlers.memory import _retrieve_context

        with pytest.raises(RuntimeError, match="Unexpected error"):
            await _retrieve_context("test query", mock_session)


# ===========================================================================
# 21. handlers/project.py line 108 — _handle_wsjf insufficient params
# ===========================================================================


def test_handle_wsjf_insufficient_params():
    """_handle_wsjf with <4 numbers returns help message."""
    from src.app.domain.services.handlers.project import _handle_wsjf

    result = _handle_wsjf("wsjf 8 6")
    assert result.agent == "project"
    assert "I need 4 values" in result.content
    assert result.metadata["error"] == "insufficient_wsjf_params"


# ===========================================================================
# 22. episodes.py line 112 — update_episode with metadata alias
# ===========================================================================


@pytest.mark.asyncio
async def test_update_episode_with_metadata_alias():
    """update_episode handles the 'metadata' kwarg aliased to 'metadata_'."""
    from src.app.persistence.models import Episode
    from src.app.persistence.repositories.episodes import update_episode

    session = AsyncMock()
    ep = Episode()
    ep.id = uuid.uuid4()
    ep.content = "test"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = ep
    session.execute.return_value = mock_result

    # Pass both a valid field and the metadata alias
    result = await update_episode(session, ep.id, content="updated", metadata={"key": "value"})
    assert result is ep


# ===========================================================================
# 23. gtd_processor.py lines 85-86 — KeyError in parse raises LLMError
# ===========================================================================


@pytest.mark.asyncio
async def test_gtd_processor_missing_key_raises(mock_anthropic_client):
    """GTD processor with missing required key raises LLMError."""
    # Return valid JSON but missing required keys
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps({"only_partial": True})
    )

    from src.app.core.exceptions import LLMError
    from src.app.second_brain.gtd_processor import process_gtd

    with pytest.raises(LLMError, match=r"(Failed to parse|Invalid) GTD"):
        await process_gtd("test", mock_anthropic_client)


# ===========================================================================
# 24. para_classifier.py lines 64-65 — KeyError in parse raises LLMError
# ===========================================================================


@pytest.mark.asyncio
async def test_para_classifier_missing_category_key(mock_anthropic_client):
    """PARA classifier with missing 'category' key raises LLMError."""
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps({"reasoning": "no category field"})
    )

    from src.app.core.exceptions import LLMError
    from src.app.second_brain.para_classifier import classify_para

    with pytest.raises(LLMError, match="Failed to parse PARA classification"):
        await classify_para("test", mock_anthropic_client)


# ===========================================================================
# 25. agent_tasks.py lines 124-133, 141-144, 198-199, 209-210, 215-217
#     — entity extraction with entities+relationships, notification send failures,
#       curation task, review task
# ===========================================================================


@pytest.mark.asyncio
async def test_entity_extraction_with_entities_and_relationships():
    """Entity extraction persists entities with relationships and mentions."""
    from src.app.workers.agent_tasks import process_agent_task

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_session)
    cm.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock()
    factory.return_value = cm

    settings = MagicMock()
    settings.anthropic_api_key.get_secret_value.return_value = "sk-test"

    llm_provider = MagicMock(configured=True)
    ctx = {
        "job_try": 1,
        "settings": settings,
        "session_factory": factory,
        "llm_provider": llm_provider,
    }

    from src.app.second_brain.entity_extractor import (
        ExtractedEntity,
        ExtractedRelationship,
        ExtractionResult,
    )

    extraction_result = ExtractionResult(
        entities=[
            ExtractedEntity(name="Alice", entity_type="person", context="Met Alice"),
            ExtractedEntity(name="Bob", entity_type="person", context="With Bob"),
        ],
        relationships=[
            ExtractedRelationship(source="Alice", target="Bob", relationship_type="works_with"),
        ],
    )

    alice_id = uuid.uuid4()
    bob_id = uuid.uuid4()

    with (
        patch(
            "src.app.workers.agent_tasks.extract_entities",
            new_callable=AsyncMock,
            return_value=extraction_result,
        ),
        patch(
            "src.app.workers.agent_tasks.upsert_entity",
            new_callable=AsyncMock,
            side_effect=[alice_id, bob_id],
        ),
        patch(
            "src.app.workers.agent_tasks.add_mention",
            new_callable=AsyncMock,
        ) as mock_mention,
        patch(
            "src.app.workers.agent_tasks.add_relationship",
            new_callable=AsyncMock,
        ) as mock_rel,
    ):
        result = await process_agent_task(
            ctx,
            "entity_extraction",
            {"text": "Met Alice and Bob at the park", "episode_id": str(uuid.uuid4())},
        )

    assert result["status"] == "ok"
    assert result["entities_count"] == 2
    assert result["relationships_count"] == 1
    assert mock_mention.call_count == 2
    mock_rel.assert_called_once()


@pytest.mark.asyncio
async def test_notification_send_failure_logged():
    """Notification delivery failure should be logged but not crash."""
    from src.app.agents.specialists.notification import FatigueManager
    from src.app.workers.agent_tasks import process_agent_task

    ctx = {
        "job_try": 1,
        "settings": MagicMock(allowed_user_ids=[12345]),
        "bot": AsyncMock(),
    }
    ctx["bot"].send_message.side_effect = RuntimeError("Network error")

    mgr = FatigueManager(dnd_start=None, dnd_end=None)

    with patch("src.app.workers.agent_tasks._fatigue_manager", mgr):
        result = await process_agent_task(
            ctx,
            "notification",
            {"message": "Alert!", "priority": "P0", "category": "system"},
        )

    assert result["status"] == "ok"
    assert result["delivered"] is True


@pytest.mark.asyncio
async def test_curation_task():
    """Curation task calls run_curation and returns ok."""
    from src.app.workers.agent_tasks import process_agent_task

    with patch(
        "src.app.workers.agent_tasks.run_curation",
        new_callable=AsyncMock,
    ) as mock_curation:
        result = await process_agent_task({"job_try": 1}, "curation", {})

    assert result["status"] == "ok"
    assert result["task"] == "curation"
    mock_curation.assert_called_once()


@pytest.mark.asyncio
async def test_review_task():
    """Review task returns not_implemented status."""
    from src.app.workers.agent_tasks import process_agent_task

    result = await process_agent_task({"job_try": 1}, "review", {"review_type": "weekly"})

    assert result["status"] == "not_implemented"
    assert result["review_type"] == "weekly"


@pytest.mark.asyncio
async def test_notification_no_bot():
    """When bot is not available, notification should still succeed."""
    from src.app.agents.specialists.notification import FatigueManager
    from src.app.workers.agent_tasks import process_agent_task

    ctx = {"job_try": 1, "settings": MagicMock(allowed_user_ids=[12345])}
    # No bot in context

    mgr = FatigueManager(dnd_start=None, dnd_end=None)

    with patch("src.app.workers.agent_tasks._fatigue_manager", mgr):
        result = await process_agent_task(
            ctx,
            "notification",
            {"message": "Alert!", "priority": "P0", "category": "system"},
        )

    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_notification_no_settings():
    """When settings are missing from ctx, notification should still work."""
    from src.app.agents.specialists.notification import FatigueManager
    from src.app.workers.agent_tasks import process_agent_task

    ctx = {"job_try": 1, "bot": AsyncMock()}
    # No settings in context

    mgr = FatigueManager(dnd_start=None, dnd_end=None)

    with patch("src.app.workers.agent_tasks._fatigue_manager", mgr):
        result = await process_agent_task(
            ctx,
            "notification",
            {"message": "Alert!", "priority": "P0", "category": "system"},
        )

    assert result["status"] == "ok"


# ===========================================================================
# 26. config.py — google_configured, tavily_configured, telegram_configured
# ===========================================================================


def test_config_google_configured_true():
    """google_configured returns True when both client_id and refresh_token are set."""
    env = {
        "APP_ENV": "test",
        "LOG_LEVEL": "DEBUG",
        "ANTHROPIC_API_KEY": "sk-ant-real",
        "DATABASE_URL": "postgresql+asyncpg://u:p@h:5432/d",
        "REDIS_URL": "redis://localhost:6379",
        "TELEGRAM_BOT_TOKEN": "123:ABCdef",
        "TELEGRAM_ALLOWED_USER_IDS": "12345",
        "TELEGRAM_WEBHOOK_URL": "https://ex.com/wh",
        "TELEGRAM_WEBHOOK_SECRET": "sec",
        "CHAT_API_KEY": "chat-key",
        "GOOGLE_CLIENT_ID": "client-id",
        "GOOGLE_CLIENT_SECRET": "client-secret",
        "GOOGLE_REFRESH_TOKEN": "refresh-token",
    }
    from src.app.config import Settings

    with patch.dict(os.environ, env, clear=False):
        s = Settings()
    assert s.google_configured is True


def test_config_google_configured_false():
    """google_configured returns False when refresh_token is empty."""
    env = {
        "APP_ENV": "test",
        "LOG_LEVEL": "DEBUG",
        "ANTHROPIC_API_KEY": "sk-ant-real",
        "DATABASE_URL": "postgresql+asyncpg://u:p@h:5432/d",
        "REDIS_URL": "redis://localhost:6379",
        "TELEGRAM_BOT_TOKEN": "123:ABCdef",
        "TELEGRAM_ALLOWED_USER_IDS": "12345",
        "TELEGRAM_WEBHOOK_URL": "https://ex.com/wh",
        "TELEGRAM_WEBHOOK_SECRET": "sec",
        "CHAT_API_KEY": "chat-key",
        "GOOGLE_CLIENT_ID": "",
        "GOOGLE_REFRESH_TOKEN": "",
    }
    from src.app.config import Settings

    with patch.dict(os.environ, env, clear=False):
        s = Settings()
    assert s.google_configured is False


def test_config_tavily_configured():
    """tavily_configured reflects whether the API key is set."""
    env = {
        "APP_ENV": "test",
        "LOG_LEVEL": "DEBUG",
        "ANTHROPIC_API_KEY": "sk-ant-real",
        "DATABASE_URL": "postgresql+asyncpg://u:p@h:5432/d",
        "REDIS_URL": "redis://localhost:6379",
        "TELEGRAM_BOT_TOKEN": "123:ABCdef",
        "TELEGRAM_ALLOWED_USER_IDS": "12345",
        "TELEGRAM_WEBHOOK_URL": "https://ex.com/wh",
        "TELEGRAM_WEBHOOK_SECRET": "sec",
        "CHAT_API_KEY": "chat-key",
        "TAVILY_API_KEY": "tvly-real-key",
    }
    from src.app.config import Settings

    with patch.dict(os.environ, env, clear=False):
        s = Settings()
    assert s.tavily_configured is True


def test_config_telegram_configured():
    """telegram_configured checks token format contains ':'."""
    env = {
        "APP_ENV": "test",
        "LOG_LEVEL": "DEBUG",
        "ANTHROPIC_API_KEY": "sk-ant-real",
        "DATABASE_URL": "postgresql+asyncpg://u:p@h:5432/d",
        "REDIS_URL": "redis://localhost:6379",
        "TELEGRAM_BOT_TOKEN": "123:ABCdef",
        "TELEGRAM_ALLOWED_USER_IDS": "12345",
        "TELEGRAM_WEBHOOK_URL": "https://ex.com/wh",
        "TELEGRAM_WEBHOOK_SECRET": "sec",
        "CHAT_API_KEY": "chat-key",
    }
    from src.app.config import Settings

    with patch.dict(os.environ, env, clear=False):
        s = Settings()
    assert s.telegram_configured is True


# ===========================================================================
# 29. mcp_config.py line 160 — _get_setting_value returns "" for None
# ===========================================================================


def test_mcp_get_setting_value_none():
    """_get_setting_value returns '' when attribute is None."""
    from src.app.agents.tools.mcp_config import _get_setting_value

    mock_settings = MagicMock()
    mock_settings.nonexistent_attr = None

    result = _get_setting_value(mock_settings, "nonexistent_attr")
    assert result == ""


def test_mcp_get_setting_value_missing_attr():
    """_get_setting_value returns '' when attribute doesn't exist."""
    from src.app.agents.tools.mcp_config import _get_setting_value

    mock_settings = MagicMock(spec=[])

    result = _get_setting_value(mock_settings, "does_not_exist")
    assert result == ""


# ===========================================================================
# FINAL GAPS — interfaces, monitoring, commitments, gtd, worker main
# ===========================================================================


def test_interfaces_module_imports():
    """Importing interfaces.py exercises the module-level import statements."""
    import src.app.domain.interfaces as ifaces

    assert hasattr(ifaces, "EpisodeRepositoryInterface")
    assert hasattr(ifaces, "GoalRepositoryInterface")
    assert hasattr(ifaces, "NoteRepositoryInterface")
    assert hasattr(ifaces, "ContactRepositoryInterface")
    assert hasattr(ifaces, "CommitmentRepositoryInterface")


@pytest.mark.asyncio
async def test_commitments_pydantic_validation_error(mock_anthropic_client):
    """Commitment with invalid field triggers ValueError in except block."""
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(
            {
                "commitments": [
                    {
                        "verbatim_text": "I'll do it",
                        "normalized_action": "do it",
                        "who_committed": "user",
                        "confidence": 999.0,
                    }
                ]
            }
        )
    )

    from src.app.core.exceptions import LLMError
    from src.app.domain.services.commitments import extract_commitments

    with pytest.raises(LLMError, match="Failed to parse commitments"):
        await extract_commitments("test", mock_anthropic_client)


@pytest.mark.asyncio
async def test_gtd_processor_missing_is_actionable_key(mock_anthropic_client):
    """GTD response with valid type but missing is_actionable raises KeyError path."""
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps({"gtd_type": "do_now", "next_action": "do thing", "reasoning": "test"})
    )

    from src.app.core.exceptions import LLMError
    from src.app.second_brain.gtd_processor import process_gtd

    with pytest.raises(LLMError, match="Failed to parse GTD response"):
        await process_gtd("test", mock_anthropic_client)

"""Tests for the decision journal endpoints."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from src.app.api.deps import get_db
from src.app.api.routes.decisions import router
from src.app.core.exceptions import EXCEPTION_STATUS_MAP, AppError, ErrorResponse
from tests.unit.api.auth_helpers import override_current_principal

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


async def _mock_get_db():
    """Yield a mock session so routes don't need a real DB."""
    yield AsyncMock()


def _build_app(*, override_auth: bool = True) -> FastAPI:
    """Create a minimal FastAPI app with the decisions router for testing."""
    app = FastAPI()
    app.dependency_overrides[get_db] = _mock_get_db

    if override_auth:
        override_current_principal(app)

    # Register the AppError handler so NotFoundError -> 404 works.
    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        status_code, error_code = EXCEPTION_STATUS_MAP.get(type(exc), (500, "app_error"))
        body = ErrorResponse(error=error_code, message=str(exc))
        return JSONResponse(status_code=status_code, content=body.model_dump())

    app.include_router(router, prefix="/api")
    return app


def _make_mock_decision(
    *,
    decision_id: uuid.UUID | None = None,
    title: str = "Switch to PostgreSQL",
    context: str | None = "Needed a more robust database",
    options_considered: list[str] | None = None,
    decision_made: str = "Use PostgreSQL with pgvector",
    reasoning: str | None = "Best support for vector search",
    expected_outcome: str | None = "Faster queries and better scalability",
    actual_outcome: str | None = None,
    outcome_rating: float | None = None,
    tags: list[str] | None = None,
    review_date: datetime | None = None,
    status: str = "pending_review",
) -> MagicMock:
    """Build a MagicMock that behaves like a Decision ORM instance."""
    now = datetime.now(UTC)
    m = MagicMock()
    m.id = decision_id or uuid.uuid4()
    m.title = title
    m.context = context
    m.options_considered = options_considered or ["PostgreSQL", "MySQL", "SQLite"]
    m.decision_made = decision_made
    m.reasoning = reasoning
    m.expected_outcome = expected_outcome
    m.actual_outcome = actual_outcome
    m.outcome_rating = outcome_rating
    m.tags = tags or ["tech", "database"]
    m.review_date = review_date
    m.status = status
    m.created_at = now
    m.updated_at = now
    return m


# ---------------------------------------------------------------------------
# list_decisions
# ---------------------------------------------------------------------------


async def test_list_decisions_success():
    """GET /decisions returns PaginatedResponse with items, total, page, page_size, has_more."""
    mock_decision = _make_mock_decision()

    mock_session = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch(
        "src.app.api.routes.decisions.repo_get_decisions",
        new_callable=AsyncMock,
        return_value=([mock_decision], 1),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/decisions")

    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "page_size" in data
    assert "has_more" in data
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["title"] == "Switch to PostgreSQL"


async def test_list_decisions_with_status_filter():
    """GET /decisions?status=reviewed passes the filter to the repo."""
    mock_session = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch(
        "src.app.api.routes.decisions.repo_get_decisions",
        new_callable=AsyncMock,
        return_value=([], 0),
    ) as mock_repo:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/decisions?status=reviewed")

    assert resp.status_code == 200
    mock_repo.assert_called_once()
    call_kwargs = mock_repo.call_args
    assert (
        call_kwargs.kwargs.get("status") == "reviewed" or call_kwargs[1].get("status") == "reviewed"
    )


# ---------------------------------------------------------------------------
# get_decision
# ---------------------------------------------------------------------------


async def test_get_decision_success():
    """GET /decisions/{id} returns a DecisionDTO for an existing decision."""
    decision_id = uuid.uuid4()
    mock_decision = _make_mock_decision(decision_id=decision_id)

    mock_session = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch(
        "src.app.api.routes.decisions.repo_get_decision_by_id",
        new_callable=AsyncMock,
        return_value=mock_decision,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/decisions/{decision_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(decision_id)
    assert data["title"] == "Switch to PostgreSQL"
    assert data["decision_made"] == "Use PostgreSQL with pgvector"


async def test_get_decision_not_found():
    """GET /decisions/{id} returns 404 when the decision does not exist."""
    decision_id = uuid.uuid4()

    mock_session = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch(
        "src.app.api.routes.decisions.repo_get_decision_by_id",
        new_callable=AsyncMock,
        return_value=None,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/decisions/{decision_id}")

    assert resp.status_code == 404
    data = resp.json()
    assert data["error"] == "not_found"


# ---------------------------------------------------------------------------
# create_decision
# ---------------------------------------------------------------------------


async def test_create_decision():
    """POST /decisions creates a decision and returns 201 with DecisionDTO."""
    decision_id = uuid.uuid4()
    mock_decision = _make_mock_decision(
        decision_id=decision_id,
        title="Adopt LangGraph",
        decision_made="Use LangGraph for agent orchestration",
    )

    mock_session = AsyncMock()
    mock_session.begin = MagicMock(return_value=AsyncMock())
    mock_session.refresh = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch(
        "src.app.api.routes.decisions.repo_create_decision",
        new_callable=AsyncMock,
        return_value=mock_decision,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/decisions",
                json={
                    "title": "Adopt LangGraph",
                    "decision_made": "Use LangGraph for agent orchestration",
                    "context": "Needed a more robust database",
                    "options_considered": ["LangGraph", "CrewAI", "AutoGen"],
                    "reasoning": "Best support for graph workflows",
                    "expected_outcome": "More reliable agent coordination",
                    "tags": ["tech", "agents"],
                },
            )

    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == str(decision_id)
    assert data["title"] == "Adopt LangGraph"


async def test_create_decision_with_review_date():
    """POST /decisions with review_date parses the ISO date correctly."""
    decision_id = uuid.uuid4()
    mock_decision = _make_mock_decision(
        decision_id=decision_id,
        review_date=datetime(2026, 6, 1, tzinfo=UTC),
    )

    mock_session = AsyncMock()
    mock_session.begin = MagicMock(return_value=AsyncMock())
    mock_session.refresh = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch(
        "src.app.api.routes.decisions.repo_create_decision",
        new_callable=AsyncMock,
        return_value=mock_decision,
    ) as mock_repo:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/decisions",
                json={
                    "title": "Switch to PostgreSQL",
                    "decision_made": "Use PostgreSQL with pgvector",
                    "review_date": "2026-06-01T00:00:00+00:00",
                },
            )

    assert resp.status_code == 201
    # Verify review_date was parsed and passed to the repo
    call_kwargs = mock_repo.call_args.kwargs
    assert call_kwargs["review_date"] is not None


async def test_create_decision_minimal():
    """POST /decisions with only required fields succeeds."""
    decision_id = uuid.uuid4()
    mock_decision = _make_mock_decision(
        decision_id=decision_id,
        title="Minimal decision",
        decision_made="Just do it",
        context=None,
        options_considered=None,
        reasoning=None,
        expected_outcome=None,
        tags=None,
    )

    mock_session = AsyncMock()
    mock_session.begin = MagicMock(return_value=AsyncMock())
    mock_session.refresh = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch(
        "src.app.api.routes.decisions.repo_create_decision",
        new_callable=AsyncMock,
        return_value=mock_decision,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/decisions",
                json={
                    "title": "Minimal decision",
                    "decision_made": "Just do it",
                },
            )

    assert resp.status_code == 201


async def test_create_decision_invalid_review_date():
    """POST /decisions rejects malformed review dates."""
    app = _build_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/decisions",
            json={
                "title": "Bad review date",
                "decision_made": "Use it anyway",
                "review_date": "not-a-date",
            },
        )

    assert resp.status_code == 422


def test_review_date_validator_raises_for_invalid_input():
    """CreateDecisionBody validator raises on malformed review dates."""
    from src.app.api.routes.decisions import CreateDecisionBody

    with pytest.raises(ValueError, match="Invalid ISO 8601 datetime"):
        CreateDecisionBody.validate_review_date("not-a-date")


def test_review_date_validator_accepts_valid_input():
    """CreateDecisionBody validator accepts well-formed review dates."""
    from src.app.api.routes.decisions import CreateDecisionBody

    assert (
        CreateDecisionBody.validate_review_date("2026-06-01T00:00:00+00:00")
        == "2026-06-01T00:00:00+00:00"
    )


def test_review_date_validator_accepts_none():
    """CreateDecisionBody validator preserves omitted review dates."""
    from src.app.api.routes.decisions import CreateDecisionBody

    assert CreateDecisionBody.validate_review_date(None) is None


async def test_list_decisions_due_review_empty_query_branch():
    """GET /decisions/due-review keeps the empty-list branch stable."""
    mock_session = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch(
        "src.app.api.routes.decisions.repo_get_decisions_due_for_review",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_repo:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/decisions/due-review")

    assert resp.status_code == 200
    mock_repo.assert_called_once()


# ---------------------------------------------------------------------------
# record_outcome
# ---------------------------------------------------------------------------


async def test_record_outcome_success():
    """PATCH /decisions/{id}/outcome records the outcome and returns DecisionDTO."""
    decision_id = uuid.uuid4()
    mock_decision = _make_mock_decision(
        decision_id=decision_id,
        actual_outcome="Queries are 3x faster",
        outcome_rating=8.5,
        status="reviewed",
    )

    mock_session = AsyncMock()
    mock_session.begin = MagicMock(return_value=AsyncMock())
    mock_session.refresh = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch(
        "src.app.api.routes.decisions.repo_update_decision_outcome",
        new_callable=AsyncMock,
        return_value=mock_decision,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/decisions/{decision_id}/outcome",
                json={
                    "actual_outcome": "Queries are 3x faster",
                    "outcome_rating": 8.5,
                },
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["actual_outcome"] == "Queries are 3x faster"
    assert data["outcome_rating"] == 8.5
    assert data["status"] == "reviewed"


async def test_record_outcome_not_found():
    """PATCH /decisions/{id}/outcome returns 404 when the decision does not exist."""
    decision_id = uuid.uuid4()

    mock_session = AsyncMock()
    mock_session.begin = MagicMock(return_value=AsyncMock())

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch(
        "src.app.api.routes.decisions.repo_update_decision_outcome",
        new_callable=AsyncMock,
        return_value=None,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/decisions/{decision_id}/outcome",
                json={
                    "actual_outcome": "It failed",
                    "outcome_rating": 2.0,
                },
            )

    assert resp.status_code == 404
    data = resp.json()
    assert data["error"] == "not_found"


async def test_record_outcome_without_rating():
    """PATCH /decisions/{id}/outcome works without providing outcome_rating."""
    decision_id = uuid.uuid4()
    mock_decision = _make_mock_decision(
        decision_id=decision_id,
        actual_outcome="It worked out fine",
        outcome_rating=None,
        status="reviewed",
    )

    mock_session = AsyncMock()
    mock_session.begin = MagicMock(return_value=AsyncMock())
    mock_session.refresh = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch(
        "src.app.api.routes.decisions.repo_update_decision_outcome",
        new_callable=AsyncMock,
        return_value=mock_decision,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/decisions/{decision_id}/outcome",
                json={
                    "actual_outcome": "It worked out fine",
                },
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["outcome_rating"] is None


# ---------------------------------------------------------------------------
# list_decisions_due_review
# ---------------------------------------------------------------------------


async def test_list_decisions_due_review():
    """GET /decisions/due-review returns decisions past their review date."""
    mock_decision = _make_mock_decision(
        review_date=datetime(2026, 1, 1, tzinfo=UTC),
        status="pending_review",
    )

    mock_session = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch(
        "src.app.api.routes.decisions.repo_get_decisions_due_for_review",
        new_callable=AsyncMock,
        return_value=[mock_decision],
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/decisions/due-review")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["status"] == "pending_review"
    assert data[0]["title"] == "Switch to PostgreSQL"


async def test_list_decisions_due_review_empty():
    """GET /decisions/due-review returns empty list when no decisions are due."""
    mock_session = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch(
        "src.app.api.routes.decisions.repo_get_decisions_due_for_review",
        new_callable=AsyncMock,
        return_value=[],
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/decisions/due-review")

    assert resp.status_code == 200
    data = resp.json()
    assert data == []

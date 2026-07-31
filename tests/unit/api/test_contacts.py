"""Tests for the contacts / CRM endpoints."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from src.app.api.deps import get_db
from src.app.api.routes.contacts import router
from src.app.core.exceptions import EXCEPTION_STATUS_MAP, AppError, ErrorResponse
from tests.unit.api.auth_helpers import override_current_principal

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


async def _mock_get_db():
    """Yield a mock session so routes don't need a real DB."""
    yield AsyncMock()


def _build_app(*, override_auth: bool = True) -> FastAPI:
    """Create a minimal FastAPI app with the contacts router for testing."""
    app = FastAPI()
    app.dependency_overrides[get_db] = _mock_get_db

    if override_auth:
        override_current_principal(app)

    # Register the AppError handler so NotFoundError → 404 works.
    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        status_code, error_code = EXCEPTION_STATUS_MAP.get(type(exc), (500, "app_error"))
        body = ErrorResponse(error=error_code, message=str(exc))
        return JSONResponse(status_code=status_code, content=body.model_dump())

    app.include_router(router, prefix="/api")
    return app


def _make_mock_contact(
    *,
    contact_id: uuid.UUID | None = None,
    first_name: str = "Alice",
    last_name: str | None = "Smith",
    email: str | None = "alice@example.com",
    tags: list[str] | None = None,
    how_we_met: str | None = "Conference",
    interaction_frequency_days: int | None = 14,
    relationship_score: float = 75.0,
) -> MagicMock:
    """Build a MagicMock that behaves like a Contact ORM instance."""
    now = datetime.now(UTC)
    m = MagicMock()
    m.id = contact_id or uuid.uuid4()
    m.first_name = first_name
    m.last_name = last_name
    m.email = email
    m.tags = tags or ["friend"]
    m.how_we_met = how_we_met
    m.interaction_frequency_days = interaction_frequency_days
    m.relationship_score = relationship_score
    m.last_interaction_at = now
    m.created_at = now
    m.updated_at = now
    return m


def _make_mock_interaction(
    *,
    contact_id: uuid.UUID | None = None,
) -> MagicMock:
    """Build a MagicMock that behaves like an Interaction ORM instance."""
    now = datetime.now(UTC)
    m = MagicMock()
    m.id = uuid.uuid4()
    m.contact_id = contact_id or uuid.uuid4()
    m.interaction_type = "meeting"
    m.direction = "outgoing"
    m.channel = "in-person"
    m.summary = "Had coffee together"
    m.topics = ["project", "catch-up"]
    m.interaction_at = now
    m.created_at = now
    return m


# ---------------------------------------------------------------------------
# list_contacts
# ---------------------------------------------------------------------------


async def test_list_contacts_success():
    """GET /contacts returns PaginatedResponse with items, total, page, page_size, has_more."""
    mock_contact = _make_mock_contact()

    mock_session = AsyncMock()

    # First execute call → count query → scalar_one() returns 1
    count_result = MagicMock()
    count_result.scalar_one.return_value = 1

    # Second execute call → contacts query → scalars().all() returns [mock_contact]
    contacts_result = MagicMock()
    contacts_result.scalars.return_value.all.return_value = [mock_contact]

    mock_session.execute = AsyncMock(side_effect=[count_result, contacts_result])

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/contacts")

    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "page_size" in data
    assert "has_more" in data
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["first_name"] == "Alice"


async def test_list_contacts_filters_and_sorting():
    """GET /contacts applies search, tag, score, and name sorting branches."""
    mock_contact = _make_mock_contact(first_name="Alicia", tags=["friend", "work"])

    mock_session = AsyncMock()
    count_result = MagicMock()
    count_result.scalar_one.return_value = 1
    contacts_result = MagicMock()
    contacts_result.scalars.return_value.all.return_value = [mock_contact]
    mock_session.execute = AsyncMock(side_effect=[count_result, contacts_result])

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/contacts",
            params={
                "search": "Ali",
                "tags": "friend, work",
                "score_min": 50,
                "score_max": 90,
                "sort": "name",
                "limit": 5,
                "offset": 2,
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["first_name"] == "Alicia"


async def test_search_contacts_endpoint():
    """GET /contacts/search returns search DTOs and hits the repository branch."""
    mock_row = {
        "id": uuid.uuid4(),
        "first_name": "Alice",
        "last_name": "Smith",
        "email": "alice@example.com",
        "tags": ["friend"],
        "relationship_score": 82.5,
    }

    mock_session = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch(
        "src.app.api.routes.contacts.repo_search_contacts",
        new_callable=AsyncMock,
        return_value=[mock_row],
    ) as mock_repo:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/contacts/search", params={"q": "Alice", "limit": 3})

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["first_name"] == "Alice"
    mock_repo.assert_called_once_with(mock_session, query="Alice", limit=3)


async def test_decaying_relationships():
    """GET /contacts/decaying exercises the decay list branch."""
    contact_id = uuid.uuid4()
    mock_contact = _make_mock_contact(contact_id=contact_id, relationship_score=24.0)

    mock_session = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch(
        "src.app.api.routes.contacts.repo_get_decaying_relationships",
        new_callable=AsyncMock,
        return_value=[mock_contact],
    ) as mock_repo:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/contacts/decaying", params={"threshold": 30, "limit": 5})

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == str(contact_id)
    mock_repo.assert_called_once_with(mock_session, threshold=30.0, limit=5)


async def test_list_contacts_empty_tags_branch():
    """GET /contacts with blank tags skips the overlap filter branch."""
    mock_contact = _make_mock_contact()

    mock_session = AsyncMock()
    count_result = MagicMock()
    count_result.scalar_one.return_value = 1
    contacts_result = MagicMock()
    contacts_result.scalars.return_value.all.return_value = [mock_contact]
    mock_session.execute = AsyncMock(side_effect=[count_result, contacts_result])

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/contacts", params={"tags": " , ", "limit": 5})

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1


def test_contact_email_validator_accepts_valid_email():
    """Validator branch accepts well-formed emails."""
    from src.app.api.routes.contacts import CreateContactBody

    assert CreateContactBody.validate_email_format("alice@example.com") == "alice@example.com"


async def test_create_contact_invalid_email():
    """POST /contacts rejects malformed email addresses."""
    app = _build_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/contacts",
            json={"first_name": "Bob", "email": "not-an-email"},
        )

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# get_contact
# ---------------------------------------------------------------------------


async def test_get_contact_success():
    """GET /contacts/{id} returns a ContactDTO for an existing contact."""
    contact_id = uuid.uuid4()
    mock_contact = _make_mock_contact(contact_id=contact_id)

    mock_session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = mock_contact
    mock_session.execute = AsyncMock(return_value=result)

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/contacts/{contact_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(contact_id)
    assert data["first_name"] == "Alice"
    assert data["relationship_score"] == 75.0


async def test_get_contact_not_found():
    """GET /contacts/{id} returns 404 when the contact does not exist."""
    contact_id = uuid.uuid4()

    mock_session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=result)

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/contacts/{contact_id}")

    assert resp.status_code == 404
    data = resp.json()
    assert data["error"] == "not_found"


async def test_list_interactions_not_found():
    """GET /contacts/{id}/interactions returns 404 when the contact does not exist."""
    contact_id = uuid.uuid4()

    mock_session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=result)

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/contacts/{contact_id}/interactions")

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# create_contact
# ---------------------------------------------------------------------------


async def test_create_contact():
    """POST /contacts creates a contact and returns 201 with ContactDTO."""
    contact_id = uuid.uuid4()
    mock_contact = _make_mock_contact(contact_id=contact_id, first_name="Bob", last_name="Jones")

    mock_session = AsyncMock()
    # session.begin() is used as ``async with session.begin():``.
    # MagicMock supports the context-manager protocol via __aenter__/__aexit__.
    mock_session.begin = MagicMock(return_value=AsyncMock())
    mock_session.refresh = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch(
        "src.app.api.routes.contacts.repo_create_contact",
        new_callable=AsyncMock,
        return_value=mock_contact,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/contacts",
                json={"first_name": "Bob", "last_name": "Jones"},
            )

    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == str(contact_id)
    assert data["first_name"] == "Bob"
    assert data["last_name"] == "Jones"


# ---------------------------------------------------------------------------
# list_contact_interactions
# ---------------------------------------------------------------------------


async def test_list_interactions():
    """GET /contacts/{id}/interactions returns a list of InteractionDTOs."""
    contact_id = uuid.uuid4()
    mock_contact = _make_mock_contact(contact_id=contact_id)
    mock_interaction = _make_mock_interaction(contact_id=contact_id)

    mock_session = AsyncMock()

    contact_result = MagicMock()
    contact_result.scalar_one_or_none.return_value = mock_contact
    # session.execute for the interactions query
    interactions_result = MagicMock()
    interactions_result.scalars.return_value.all.return_value = [mock_interaction]
    mock_session.execute = AsyncMock(side_effect=[contact_result, interactions_result])

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/contacts/{contact_id}/interactions")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["interaction_type"] == "meeting"
    assert data[0]["contact_id"] == str(contact_id)


# ---------------------------------------------------------------------------
# log_interaction
# ---------------------------------------------------------------------------


async def test_log_interaction():
    """POST /contacts/{id}/interactions logs an interaction and returns 201."""
    contact_id = uuid.uuid4()
    mock_contact = _make_mock_contact(contact_id=contact_id)
    mock_interaction = _make_mock_interaction(contact_id=contact_id)

    mock_session = AsyncMock()
    contact_result = MagicMock()
    contact_result.scalar_one_or_none.return_value = mock_contact
    mock_session.execute = AsyncMock(return_value=contact_result)
    mock_session.begin = MagicMock(return_value=AsyncMock())
    mock_session.refresh = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch(
        "src.app.api.routes.contacts.repo_log_interaction",
        new_callable=AsyncMock,
        return_value=mock_interaction,
    ) as repo_log:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/contacts/{contact_id}/interactions",
                json={
                    "interaction_type": "meeting",
                    "direction": "outgoing",
                    "channel": "in-person",
                    "summary": "Had coffee together",
                    "topics": ["project", "catch-up"],
                    "interaction_at": "2026-03-16T10:30:00+01:00",
                },
            )

    assert resp.status_code == 201
    data = resp.json()
    assert data["interaction_type"] == "meeting"
    assert data["contact_id"] == str(contact_id)
    assert data["summary"] == "Had coffee together"
    assert repo_log.await_args.kwargs["interaction_at"] == datetime(
        2026,
        3,
        16,
        9,
        30,
        tzinfo=UTC,
    )


async def test_log_interaction_not_found():
    """POST /contacts/{id}/interactions returns 404 when the contact does not exist."""
    contact_id = uuid.uuid4()

    mock_session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=result)

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/contacts/{contact_id}/interactions",
            json={
                "interaction_type": "meeting",
                "direction": "outgoing",
                "summary": "No contact exists",
            },
        )

    assert resp.status_code == 404

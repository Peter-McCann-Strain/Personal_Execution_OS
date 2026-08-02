"""Tests to fill all remaining API-route coverage gaps.

Each section targets specific missing lines identified by coverage analysis.
Gaps 8-16 and 28 from the master coverage list.
"""

import uuid
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from src.app.api.deps import get_db
from src.app.core.exceptions import EXCEPTION_STATUS_MAP, AppError, ErrorResponse
from tests.unit.api.auth_helpers import override_current_principal

# ===========================================================================
# Shared helpers
# ===========================================================================


def _base_app(router, *, prefix: str = "/api") -> FastAPI:
    """Build a minimal FastAPI app with the given router and standard overrides."""
    app = FastAPI()

    async def _mock_get_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = _mock_get_db

    override_current_principal(app)

    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        status_code, error_code = EXCEPTION_STATUS_MAP.get(type(exc), (500, "app_error"))
        body = ErrorResponse(error=error_code, message=str(exc))
        return JSONResponse(status_code=status_code, content=body.model_dump())

    app.include_router(router, prefix=prefix)
    return app


def _app_with_session(router, mock_session, *, prefix: str = "/api") -> FastAPI:
    """Build a test app with a specific mock session injected."""
    app = _base_app(router, prefix=prefix)

    async def _mock_db():
        yield mock_session

    app.dependency_overrides[get_db] = _mock_db
    return app


# ===========================================================================
# Gap 8: contacts.py — _fmt_dt None, list_contacts filters, interactions not found
# Lines: 86, 141-142, 147-149, 152, 154, 224, 250
# ===========================================================================


def _make_mock_contact(
    *,
    contact_id=None,
    first_name="Alice",
    last_name="Smith",
    email="alice@example.com",
    tags=None,
    relationship_score=75.0,
    last_interaction_at=None,
):
    now = datetime.now(UTC)
    m = MagicMock()
    m.id = contact_id or uuid.uuid4()
    m.first_name = first_name
    m.last_name = last_name
    m.email = email
    m.tags = tags or ["friend"]
    m.how_we_met = "Conference"
    m.interaction_frequency_days = 14
    m.relationship_score = relationship_score
    m.last_interaction_at = last_interaction_at  # None to test _fmt_dt(None) => None
    m.created_at = now
    m.updated_at = now
    return m


async def test_contacts_fmt_dt_returns_none():
    """_fmt_dt returns None when given None (line 86)."""
    from src.app.api.routes.contacts import _fmt_dt

    assert _fmt_dt(None) is None


async def test_contacts_fmt_dt_returns_iso():
    """_fmt_dt returns ISO string for a datetime."""
    from src.app.api.routes.contacts import _fmt_dt

    dt = datetime(2026, 3, 16, 12, 0, 0, tzinfo=UTC)
    assert _fmt_dt(dt) == dt.isoformat()


async def test_list_contacts_with_search_filter():
    """GET /contacts?search=... exercises the search/ilike branch (lines 141-142)."""
    from src.app.api.routes.contacts import router

    mock_contact = _make_mock_contact()
    mock_session = AsyncMock()

    count_result = MagicMock()
    count_result.scalar_one.return_value = 1

    contacts_result = MagicMock()
    contacts_result.scalars.return_value.all.return_value = [mock_contact]

    mock_session.execute = AsyncMock(side_effect=[count_result, contacts_result])

    app = _app_with_session(router, mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/contacts", params={"search": "alice"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1


async def test_list_contacts_with_tags_filter():
    """GET /contacts?tags=friend,work exercises the tags overlap branch (lines 147-149)."""
    from src.app.api.routes.contacts import router

    mock_contact = _make_mock_contact()
    mock_session = AsyncMock()

    count_result = MagicMock()
    count_result.scalar_one.return_value = 1

    contacts_result = MagicMock()
    contacts_result.scalars.return_value.all.return_value = [mock_contact]

    mock_session.execute = AsyncMock(side_effect=[count_result, contacts_result])

    app = _app_with_session(router, mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/contacts", params={"tags": "friend,work"})

    assert resp.status_code == 200


async def test_list_contacts_with_score_filters():
    """GET /contacts?score_min=10&score_max=90 exercises both score filters (lines 152, 154)."""
    from src.app.api.routes.contacts import router

    mock_contact = _make_mock_contact(relationship_score=50.0)
    mock_session = AsyncMock()

    count_result = MagicMock()
    count_result.scalar_one.return_value = 1

    contacts_result = MagicMock()
    contacts_result.scalars.return_value.all.return_value = [mock_contact]

    mock_session.execute = AsyncMock(side_effect=[count_result, contacts_result])

    app = _app_with_session(router, mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/contacts", params={"score_min": 10, "score_max": 90})

    assert resp.status_code == 200


async def test_list_contact_interactions_not_found():
    """GET /contacts/{id}/interactions returns 404 when contact doesn't exist (line 224)."""
    from src.app.api.routes.contacts import router

    contact_id = uuid.uuid4()
    mock_session = AsyncMock()
    contact_result = MagicMock()
    contact_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=contact_result)

    app = _app_with_session(router, mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/contacts/{contact_id}/interactions")

    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"


async def test_log_interaction_contact_not_found():
    """POST /contacts/{id}/interactions returns 404 when contact doesn't exist (line 250)."""
    from src.app.api.routes.contacts import router

    contact_id = uuid.uuid4()
    mock_session = AsyncMock()
    contact_result = MagicMock()
    contact_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=contact_result)

    app = _app_with_session(router, mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/contacts/{contact_id}/interactions",
            json={
                "interaction_type": "meeting",
                "direction": "outgoing",
                "summary": "Coffee",
            },
        )

    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"


async def test_contact_dto_with_none_last_interaction():
    """ContactDTO created from contact with last_interaction_at=None covers _fmt_dt(None) path."""
    from src.app.api.routes.contacts import _contact_to_dto

    mock_contact = _make_mock_contact(last_interaction_at=None)
    dto = _contact_to_dto(mock_contact)
    assert dto.last_interaction_at is None


# ===========================================================================
# Gap 9: calendar.py — _make_calendar_service and event filtering
# ===========================================================================


async def test_calendar_make_calendar_service():
    """_make_calendar_service creates a CalendarService from settings (lines 86-89)."""
    mock_settings = MagicMock()
    mock_settings.google_client_id = "cid"
    mock_settings.google_client_secret = MagicMock()
    mock_settings.google_client_secret.get_secret_value.return_value = "secret"
    mock_settings.google_refresh_token = MagicMock()
    mock_settings.google_refresh_token.get_secret_value.return_value = "token"

    with (
        patch("src.app.api.routes.calendar.get_settings", return_value=mock_settings),
        patch("src.app.agents.tools.calendar.CalendarService") as mock_cls,
    ):
        from src.app.api.routes.calendar import _make_calendar_service

        _make_calendar_service()
        mock_cls.assert_called_once_with(
            client_id="cid",
            client_secret="secret",
            refresh_token="token",
        )


async def test_calendar_get_events_with_date_objects():
    """GET /calendar/events handles date objects (not datetime) in event (lines 155, 159)."""
    from src.app.api.routes.calendar import router

    # Event with date objects (all-day events) instead of datetime
    mock_event = MagicMock()
    mock_event.id = "ev_allday"
    mock_event.summary = "All-day event"
    mock_event.start = date(2026, 3, 16)  # date, not datetime
    mock_event.end = date(2026, 3, 17)  # date, not datetime
    mock_event.location = None
    mock_event.description = None
    mock_event.attendees = []

    mock_service = AsyncMock()
    mock_service.get_upcoming_events = AsyncMock(return_value=[mock_event])
    mock_service.close = AsyncMock()

    app = _base_app(router)

    with (
        patch("src.app.api.routes.calendar._check_google_configured"),
        patch("src.app.api.routes.calendar._make_calendar_service", return_value=mock_service),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/calendar/events",
                params={
                    "start": "2026-03-15T00:00:00Z",
                    "end": "2026-03-18T00:00:00Z",
                },
            )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == "ev_allday"


async def test_calendar_get_events_with_naive_datetime():
    """GET /calendar/events handles naive datetime in event start/end (lines 157, 161)."""
    from src.app.api.routes.calendar import router

    # Event with naive datetimes (no tz info)
    mock_event = MagicMock()
    mock_event.id = "ev_naive"
    mock_event.summary = "Naive event"
    mock_event.start = datetime(2026, 3, 16, 9, 0, 0)  # naive datetime
    mock_event.end = datetime(2026, 3, 16, 10, 0, 0)  # naive datetime
    mock_event.location = None
    mock_event.description = None
    mock_event.attendees = []

    mock_service = AsyncMock()
    mock_service.get_upcoming_events = AsyncMock(return_value=[mock_event])
    mock_service.close = AsyncMock()

    app = _base_app(router)

    with (
        patch("src.app.api.routes.calendar._check_google_configured"),
        patch("src.app.api.routes.calendar._make_calendar_service", return_value=mock_service),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/calendar/events",
                params={
                    "start": "2026-03-15T00:00:00Z",
                    "end": "2026-03-17T00:00:00Z",
                },
            )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == "ev_naive"


# ===========================================================================
# Gap 10: email.py — _make_gmail_service and inbox query filters
# ===========================================================================


async def test_email_make_gmail_service():
    """_make_gmail_service creates a GmailService from settings (lines 84-87)."""
    mock_settings = MagicMock()
    mock_settings.google_client_id = "cid"
    mock_settings.google_client_secret = MagicMock()
    mock_settings.google_client_secret.get_secret_value.return_value = "secret"
    mock_settings.google_refresh_token = MagicMock()
    mock_settings.google_refresh_token.get_secret_value.return_value = "token"

    with (
        patch("src.app.api.routes.email.get_settings", return_value=mock_settings),
        patch("src.app.agents.tools.email.GmailService") as mock_cls,
    ):
        from src.app.api.routes.email import _make_gmail_service

        _make_gmail_service()
        mock_cls.assert_called_once_with(
            client_id="cid",
            client_secret="secret",
            refresh_token="token",
        )


async def test_email_inbox_with_search_filter():
    """GET /email/inbox?search=... appends search to query (line 147)."""
    from src.app.api.routes.email import router

    mock_service = AsyncMock()
    mock_service.search_emails = AsyncMock(return_value=[])
    mock_service.close = AsyncMock()

    app = _base_app(router)

    with (
        patch("src.app.api.routes.email._check_google_configured"),
        patch("src.app.api.routes.email._make_gmail_service", return_value=mock_service),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/email/inbox", params={"search": "invoice"})

    assert resp.status_code == 200
    # Verify the search term was included in the Gmail query
    call_kwargs = mock_service.search_emails.call_args.kwargs
    assert "invoice" in call_kwargs["query"]


async def test_email_inbox_with_unread_only():
    """GET /email/inbox?unread_only=true appends is:unread to query (line 149)."""
    from src.app.api.routes.email import router

    mock_service = AsyncMock()
    mock_service.search_emails = AsyncMock(return_value=[])
    mock_service.close = AsyncMock()

    app = _base_app(router)

    with (
        patch("src.app.api.routes.email._check_google_configured"),
        patch("src.app.api.routes.email._make_gmail_service", return_value=mock_service),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/email/inbox", params={"unread_only": True})

    assert resp.status_code == 200
    call_kwargs = mock_service.search_emails.call_args.kwargs
    assert "is:unread" in call_kwargs["query"]


async def test_email_inbox_with_triage_filter():
    """GET /email/inbox?triage=urgent appends label:urgent to query (line 152)."""
    from src.app.api.routes.email import router

    mock_service = AsyncMock()
    mock_service.search_emails = AsyncMock(return_value=[])
    mock_service.close = AsyncMock()

    app = _base_app(router)

    with (
        patch("src.app.api.routes.email._check_google_configured"),
        patch("src.app.api.routes.email._make_gmail_service", return_value=mock_service),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/email/inbox", params={"triage": "urgent"})

    assert resp.status_code == 200
    call_kwargs = mock_service.search_emails.call_args.kwargs
    assert "label:urgent" in call_kwargs["query"]


# ===========================================================================
# Gap 11: projects.py — _milestone_to_dto, _epic_to_dto, get_project with
#          full hierarchy, create_project with deadline, update_task status transitions
# Lines: 146, 162, 273-309, 320, 344, 348, 350, 352
# ===========================================================================


def _make_mock_project(
    *, project_id=None, title="Test Project", deadline=None, status="in-progress"
):
    now = datetime.now(UTC)
    m = MagicMock()
    m.id = project_id or uuid.uuid4()
    m.title = title
    m.description = "A test project"
    m.status = status
    m.appetite = "big-batch"
    m.deadline = deadline
    m.created_at = now
    m.updated_at = now
    return m


def _make_mock_epic(*, epic_id=None, project_id=None):
    now = datetime.now(UTC)
    m = MagicMock()
    m.id = epic_id or uuid.uuid4()
    m.project_id = project_id or uuid.uuid4()
    m.title = "Epic One"
    m.description = "First epic"
    m.sort_order = 1
    m.created_at = now
    return m


def _make_mock_milestone(*, milestone_id=None, epic_id=None):
    now = datetime.now(UTC)
    m = MagicMock()
    m.id = milestone_id or uuid.uuid4()
    m.epic_id = epic_id or uuid.uuid4()
    m.title = "Milestone One"
    m.success_criteria = "All tasks done"
    m.sort_order = 1
    m.created_at = now
    return m


def _make_mock_task(*, task_id=None, milestone_id=None, title="Task One", status="todo"):
    now = datetime.now(UTC)
    m = MagicMock()
    m.id = task_id or uuid.uuid4()
    m.milestone_id = milestone_id or uuid.uuid4()
    m.title = title
    m.description = None
    m.status = status
    m.estimate_hours = 4.0
    m.actual_hours = None
    m.wsjf_score = None
    m.complexity = None
    m.context_tags = ["dev"]
    m.sort_order = 1
    m.started_at = None
    m.completed_at = None
    m.created_at = now
    m.updated_at = now
    return m


def _make_task_update_result(task):
    result = MagicMock()
    result.scalar_one_or_none.return_value = task
    return result


async def test_milestone_to_dto():
    """_milestone_to_dto converts a Milestone + tasks to MilestoneDTO (line 146)."""
    from src.app.api.routes.projects import _milestone_to_dto

    ms_id = uuid.uuid4()
    epic_id = uuid.uuid4()
    ms = _make_mock_milestone(milestone_id=ms_id, epic_id=epic_id)
    task = _make_mock_task(milestone_id=ms_id)

    dto = _milestone_to_dto(ms, [task])
    assert dto.id == str(ms_id)
    assert dto.title == "Milestone One"
    assert len(dto.tasks) == 1
    assert dto.tasks[0].title == "Task One"


async def test_epic_to_dto():
    """_epic_to_dto converts an Epic + milestones + tasks dict to EpicDTO (line 162)."""
    from src.app.api.routes.projects import _epic_to_dto

    epic_id = uuid.uuid4()
    project_id = uuid.uuid4()
    ms_id = uuid.uuid4()

    epic = _make_mock_epic(epic_id=epic_id, project_id=project_id)
    ms = _make_mock_milestone(milestone_id=ms_id, epic_id=epic_id)
    task = _make_mock_task(milestone_id=ms_id)

    dto = _epic_to_dto(epic, [ms], {ms_id: [task]})
    assert dto.id == str(epic_id)
    assert dto.title == "Epic One"
    assert len(dto.milestones) == 1
    assert len(dto.milestones[0].tasks) == 1


async def test_get_project_with_full_hierarchy():
    """GET /projects/{id} with epics, milestones, tasks (lines 273-309)."""
    from src.app.api.routes.projects import router

    project_id = uuid.uuid4()
    epic_id = uuid.uuid4()
    ms_id = uuid.uuid4()
    task_id = uuid.uuid4()

    mock_project = _make_mock_project(project_id=project_id)
    mock_epic = _make_mock_epic(epic_id=epic_id, project_id=project_id)
    mock_ms = _make_mock_milestone(milestone_id=ms_id, epic_id=epic_id)
    mock_task = _make_mock_task(task_id=task_id, milestone_id=ms_id)

    mock_session = AsyncMock()
    project_result = MagicMock()
    project_result.scalar_one_or_none.return_value = mock_project

    # Epics query result
    epics_result = MagicMock()
    epics_result.scalars.return_value.all.return_value = [mock_epic]

    # Milestones query result
    milestones_result = MagicMock()
    milestones_result.scalars.return_value.all.return_value = [mock_ms]

    # Tasks query result
    tasks_result = MagicMock()
    tasks_result.scalars.return_value.all.return_value = [mock_task]

    dependencies_result = MagicMock()
    dependencies_result.scalars.return_value.all.return_value = []

    mock_session.execute = AsyncMock(
        side_effect=[
            project_result,
            epics_result,
            milestones_result,
            tasks_result,
            dependencies_result,
        ]
    )

    app = _app_with_session(router, mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/projects/{project_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(project_id)
    assert len(data["epics"]) == 1
    assert len(data["epics"][0]["milestones"]) == 1
    assert len(data["epics"][0]["milestones"][0]["tasks"]) == 1
    assert data["epics"][0]["milestones"][0]["tasks"][0]["id"] == str(task_id)


async def test_create_project_with_deadline():
    """POST /projects with deadline parses it (line 320)."""
    from src.app.api.routes.projects import router

    project_id = uuid.uuid4()
    mock_project = _make_mock_project(
        project_id=project_id,
        deadline=datetime(2026, 6, 1, tzinfo=UTC),
    )
    mock_session = AsyncMock()

    app = _app_with_session(router, mock_session)

    with patch(
        "src.app.api.routes.projects.create_project",
        new_callable=AsyncMock,
        return_value=mock_project,
    ) as mock_create:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/projects",
                json={
                    "title": "Deadline Project",
                    "deadline": "2026-06-01T00:00:00+00:00",
                },
            )

    assert resp.status_code == 201
    data = resp.json()
    assert data["deadline"] is not None
    # Verify deadline was parsed and passed to create_project
    _, kwargs = mock_create.call_args
    assert kwargs["deadline"] is not None


async def test_update_task_with_title():
    """PATCH /tasks/{id} with title updates title (line 344)."""
    from src.app.api.routes.projects import router

    task_id = uuid.uuid4()
    mock_task = _make_mock_task(task_id=task_id, title="Updated Title")

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_task)
    mock_session.execute = AsyncMock(return_value=_make_task_update_result(mock_task))
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    app = _app_with_session(router, mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch(
            f"/api/tasks/{task_id}",
            json={"title": "Updated Title"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Updated Title"


async def test_update_task_with_estimate_hours():
    """PATCH /tasks/{id} with estimate_hours (line 348)."""
    from src.app.api.routes.projects import router

    task_id = uuid.uuid4()
    mock_task = _make_mock_task(task_id=task_id)
    mock_task.estimate_hours = 8.0

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_task)
    mock_session.execute = AsyncMock(return_value=_make_task_update_result(mock_task))
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    app = _app_with_session(router, mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch(
            f"/api/tasks/{task_id}",
            json={"estimate_hours": 8.0},
        )

    assert resp.status_code == 200


async def test_update_task_with_wsjf_score():
    """PATCH /tasks/{id} with wsjf_score (line 350)."""
    from src.app.api.routes.projects import router

    task_id = uuid.uuid4()
    mock_task = _make_mock_task(task_id=task_id)
    mock_task.wsjf_score = 42.0

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_task)
    mock_session.execute = AsyncMock(return_value=_make_task_update_result(mock_task))
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    app = _app_with_session(router, mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch(
            f"/api/tasks/{task_id}",
            json={"wsjf_score": 42.0},
        )

    assert resp.status_code == 200


async def test_update_task_with_context_tags():
    """PATCH /tasks/{id} with context_tags (line 352)."""
    from src.app.api.routes.projects import router

    task_id = uuid.uuid4()
    mock_task = _make_mock_task(task_id=task_id)
    mock_task.context_tags = ["backend", "search"]

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_task)
    mock_session.execute = AsyncMock(return_value=_make_task_update_result(mock_task))
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    app = _app_with_session(router, mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch(
            f"/api/tasks/{task_id}",
            json={"context_tags": ["backend", "search"]},
        )

    assert resp.status_code == 200


async def test_update_task_in_progress_status():
    """PATCH /tasks/{id} with status=in_progress sets started_at (line 360 branch)."""
    from src.app.api.routes.projects import router

    task_id = uuid.uuid4()
    mock_task = _make_mock_task(task_id=task_id, status="in_progress")

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_task)
    mock_session.execute = AsyncMock(return_value=_make_task_update_result(mock_task))
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    app = _app_with_session(router, mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch(
            f"/api/tasks/{task_id}",
            json={"status": "in_progress"},
        )

    assert resp.status_code == 200


async def test_update_task_done_status():
    """PATCH /tasks/{id} with status=done sets completed_at (line 362 branch)."""
    from src.app.api.routes.projects import router

    task_id = uuid.uuid4()
    mock_task = _make_mock_task(task_id=task_id, status="done")
    mock_task.completed_at = datetime.now(UTC)

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_task)
    mock_session.execute = AsyncMock(return_value=_make_task_update_result(mock_task))
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    app = _app_with_session(router, mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch(
            f"/api/tasks/{task_id}",
            json={"status": "done"},
        )

    assert resp.status_code == 200


# ===========================================================================
# Gap 12: goals.py — list_goals with status/goal_type filters, desc ordering
# Lines: 93, 95, 104
# ===========================================================================


async def test_list_goals_with_status_filter():
    """GET /goals?status=active exercises the status filter branch (line 93)."""
    from src.app.api.routes.goals import router

    mock_session = AsyncMock()

    count_result = MagicMock()
    count_result.scalar_one.return_value = 0

    data_result = MagicMock()
    data_result.scalars.return_value.all.return_value = []

    mock_session.execute = AsyncMock(side_effect=[count_result, data_result])

    app = _app_with_session(router, mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/goals", params={"status": "active"})

    assert resp.status_code == 200
    assert resp.json()["total"] == 0


async def test_list_goals_with_goal_type_filter():
    """GET /goals?goal_type=quarterly exercises the goal_type filter (line 95)."""
    from src.app.api.routes.goals import router

    mock_session = AsyncMock()

    count_result = MagicMock()
    count_result.scalar_one.return_value = 0

    data_result = MagicMock()
    data_result.scalars.return_value.all.return_value = []

    mock_session.execute = AsyncMock(side_effect=[count_result, data_result])

    app = _app_with_session(router, mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/goals", params={"goal_type": "quarterly"})

    assert resp.status_code == 200


async def test_list_goals_desc_order():
    """GET /goals?order=desc exercises the desc ordering branch (line 104)."""
    from src.app.api.routes.goals import router

    mock_session = AsyncMock()

    count_result = MagicMock()
    count_result.scalar_one.return_value = 0

    data_result = MagicMock()
    data_result.scalars.return_value.all.return_value = []

    mock_session.execute = AsyncMock(side_effect=[count_result, data_result])

    app = _app_with_session(router, mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/goals", params={"order": "desc", "sort": "progress"})

    assert resp.status_code == 200


# ===========================================================================
# Gap 13: reviews.py — list with type filter, generate quarterly, mood branches
# Lines: 114, 166-167, 180-181, 190-195
# ===========================================================================


async def test_list_reviews_with_type_filter():
    """GET /reviews?review_type=weekly exercises the type filter (line 114)."""
    from src.app.api.routes.reviews import router

    mock_session = AsyncMock()

    count_result = MagicMock()
    count_result.scalar_one.return_value = 0

    data_result = MagicMock()
    data_result.scalars.return_value.all.return_value = []

    mock_session.execute = AsyncMock(side_effect=[count_result, data_result])

    app = _app_with_session(router, mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/reviews", params={"review_type": "weekly"})

    assert resp.status_code == 200


async def test_generate_review_quarterly():
    """POST /reviews/generate type=quarterly uses 90-day period (lines 166-167)."""
    from src.app.api.routes.reviews import router

    generated_id = uuid.uuid4()
    mock_session = AsyncMock()

    # Episodes, goals, commitments queries
    episodes_result = MagicMock()
    episodes_result.scalars.return_value.all.return_value = []

    goals_result = MagicMock()
    goals_result.scalars.return_value.all.return_value = []

    commitments_result = MagicMock()
    commitments_result.scalars.return_value.all.return_value = []

    mock_session.execute = AsyncMock(
        side_effect=[episodes_result, goals_result, commitments_result]
    )
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    def _side_effect_add(review_obj):
        review_obj.id = generated_id
        review_obj.created_at = datetime(2026, 3, 16, 12, 0, 0, tzinfo=UTC)

    mock_session.add.side_effect = _side_effect_add

    app = _app_with_session(router, mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/reviews/generate", json={"type": "quarterly"})

    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == str(generated_id)


async def test_generate_review_with_mood_high():
    """POST /reviews/generate with high mood episodes => 'Generally positive' (line 191)."""
    from src.app.api.routes.reviews import router

    generated_id = uuid.uuid4()
    mock_session = AsyncMock()

    # Episodes with high mood
    mock_ep = MagicMock()
    mock_ep.summary = "Great day"
    mock_ep.mood_score = 8.5

    episodes_result = MagicMock()
    episodes_result.scalars.return_value.all.return_value = [mock_ep]

    goals_result = MagicMock()
    goals_result.scalars.return_value.all.return_value = []

    commitments_result = MagicMock()
    commitments_result.scalars.return_value.all.return_value = []

    mock_session.execute = AsyncMock(
        side_effect=[episodes_result, goals_result, commitments_result]
    )
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    def _side_effect_add(review_obj):
        review_obj.id = generated_id
        review_obj.created_at = datetime(2026, 3, 16, 12, 0, 0, tzinfo=UTC)

    mock_session.add.side_effect = _side_effect_add

    app = _app_with_session(router, mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/reviews/generate", json={"type": "weekly"})

    assert resp.status_code == 201
    data = resp.json()
    assert "positive" in data["mood_summary"].lower()
    assert data["average_mood"] == 8.5


async def test_generate_review_with_mood_medium():
    """POST /reviews/generate with medium mood => 'Mixed mood' (lines 192-193)."""
    from src.app.api.routes.reviews import router

    generated_id = uuid.uuid4()
    mock_session = AsyncMock()

    mock_ep = MagicMock()
    mock_ep.summary = "Average day"
    mock_ep.mood_score = 5.0

    episodes_result = MagicMock()
    episodes_result.scalars.return_value.all.return_value = [mock_ep]

    goals_result = MagicMock()
    goals_result.scalars.return_value.all.return_value = []

    commitments_result = MagicMock()
    commitments_result.scalars.return_value.all.return_value = []

    mock_session.execute = AsyncMock(
        side_effect=[episodes_result, goals_result, commitments_result]
    )
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    def _side_effect_add(review_obj):
        review_obj.id = generated_id
        review_obj.created_at = datetime(2026, 3, 16, 12, 0, 0, tzinfo=UTC)

    mock_session.add.side_effect = _side_effect_add

    app = _app_with_session(router, mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/reviews/generate", json={"type": "weekly"})

    assert resp.status_code == 201
    data = resp.json()
    assert "mixed" in data["mood_summary"].lower()


async def test_generate_review_with_mood_low():
    """POST /reviews/generate with low mood => 'lower than usual' (lines 194-195)."""
    from src.app.api.routes.reviews import router

    generated_id = uuid.uuid4()
    mock_session = AsyncMock()

    mock_ep = MagicMock()
    mock_ep.summary = "Rough day"
    mock_ep.mood_score = 2.0

    episodes_result = MagicMock()
    episodes_result.scalars.return_value.all.return_value = [mock_ep]

    goals_result = MagicMock()
    goals_result.scalars.return_value.all.return_value = []

    commitments_result = MagicMock()
    commitments_result.scalars.return_value.all.return_value = []

    mock_session.execute = AsyncMock(
        side_effect=[episodes_result, goals_result, commitments_result]
    )
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    def _side_effect_add(review_obj):
        review_obj.id = generated_id
        review_obj.created_at = datetime(2026, 3, 16, 12, 0, 0, tzinfo=UTC)

    mock_session.add.side_effect = _side_effect_add

    app = _app_with_session(router, mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/reviews/generate", json={"type": "weekly"})

    assert resp.status_code == 201
    data = resp.json()
    assert "lower" in data["mood_summary"].lower()


async def test_generate_review_with_episode_content_fallback():
    """POST /reviews/generate episode has content but no summary => uses content[:200] (line 181)."""
    from src.app.api.routes.reviews import router

    generated_id = uuid.uuid4()
    mock_session = AsyncMock()

    mock_ep = MagicMock()
    mock_ep.summary = None  # No summary
    mock_ep.mood_score = None

    episodes_result = MagicMock()
    episodes_result.scalars.return_value.all.return_value = [mock_ep]

    goals_result = MagicMock()
    goals_result.scalars.return_value.all.return_value = []

    commitments_result = MagicMock()
    commitments_result.scalars.return_value.all.return_value = []

    mock_session.execute = AsyncMock(
        side_effect=[episodes_result, goals_result, commitments_result]
    )
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    def _side_effect_add(review_obj):
        review_obj.id = generated_id
        review_obj.created_at = datetime(2026, 3, 16, 12, 0, 0, tzinfo=UTC)

    mock_session.add.side_effect = _side_effect_add

    app = _app_with_session(router, mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/reviews/generate", json={"type": "weekly"})

    assert resp.status_code == 201
    data = resp.json()
    # No summary means no accomplishments added
    assert data["accomplishments"] == []


# ===========================================================================
# Gap 14: notifications.py — list with priority/category/status filters, dismiss not found
# Lines: 80-82, 85, 88, 114
# ===========================================================================


async def test_list_notifications_with_priority_filter():
    """GET /notifications?priority=P0,P1 exercises priority filter (lines 80-82)."""
    from src.app.api.routes.notifications import router

    mock_session = AsyncMock()

    count_result = MagicMock()
    count_result.scalar_one.return_value = 0

    data_result = MagicMock()
    data_result.scalars.return_value.all.return_value = []

    mock_session.execute = AsyncMock(side_effect=[count_result, data_result])

    app = _app_with_session(router, mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/notifications", params={"priority": "P0,P1"})

    assert resp.status_code == 200


async def test_list_notifications_with_category_filter():
    """GET /notifications?category=relationship exercises category filter (line 85)."""
    from src.app.api.routes.notifications import router

    mock_session = AsyncMock()

    count_result = MagicMock()
    count_result.scalar_one.return_value = 0

    data_result = MagicMock()
    data_result.scalars.return_value.all.return_value = []

    mock_session.execute = AsyncMock(side_effect=[count_result, data_result])

    app = _app_with_session(router, mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/notifications", params={"category": "relationship"})

    assert resp.status_code == 200


async def test_list_notifications_with_status_filter():
    """GET /notifications?status=unread exercises status filter (line 88)."""
    from src.app.api.routes.notifications import router

    mock_session = AsyncMock()

    count_result = MagicMock()
    count_result.scalar_one.return_value = 0

    data_result = MagicMock()
    data_result.scalars.return_value.all.return_value = []

    mock_session.execute = AsyncMock(side_effect=[count_result, data_result])

    app = _app_with_session(router, mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/notifications", params={"status": "unread"})

    assert resp.status_code == 200


async def test_dismiss_notification_not_found():
    """PATCH /notifications/{id}/dismiss returns 404 when not found (line 114)."""
    from src.app.api.routes.notifications import router

    notif_id = uuid.uuid4()
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=None)

    app = _app_with_session(router, mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch(f"/api/notifications/{notif_id}/dismiss")

    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"


# ===========================================================================
# Gap 15: dashboard.py — morning_briefing afternoon/evening greeting branches
# Lines: 214, 216
# ===========================================================================


async def test_morning_briefing_afternoon():
    """GET /dashboard/briefing at 14:00 UTC returns 'Good afternoon' (line 216)."""
    from src.app.api.routes.dashboard import router

    mock_session = AsyncMock()
    app = _app_with_session(router, mock_session)

    afternoon_time = datetime(2026, 3, 16, 14, 0, 0, tzinfo=UTC)
    with patch("src.app.api.routes.dashboard.datetime") as mock_dt:
        mock_dt.now.return_value = afternoon_time
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/dashboard/briefing")

    assert resp.status_code == 200
    data = resp.json()
    assert data["greeting"]["greeting"] == "Good afternoon"


async def test_morning_briefing_evening():
    """GET /dashboard/briefing at 20:00 UTC returns 'Good evening' (line 218)."""
    from src.app.api.routes.dashboard import router

    mock_session = AsyncMock()
    app = _app_with_session(router, mock_session)

    evening_time = datetime(2026, 3, 16, 20, 0, 0, tzinfo=UTC)
    with patch("src.app.api.routes.dashboard.datetime") as mock_dt:
        mock_dt.now.return_value = evening_time
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/dashboard/briefing")

    assert resp.status_code == 200
    data = resp.json()
    assert data["greeting"]["greeting"] == "Good evening"


async def test_morning_briefing_morning():
    """GET /dashboard/briefing at 08:00 UTC returns 'Good morning' (line 214)."""
    from src.app.api.routes.dashboard import router

    mock_session = AsyncMock()
    app = _app_with_session(router, mock_session)

    morning_time = datetime(2026, 3, 16, 8, 0, 0, tzinfo=UTC)
    with patch("src.app.api.routes.dashboard.datetime") as mock_dt:
        mock_dt.now.return_value = morning_time
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/dashboard/briefing")

    assert resp.status_code == 200
    data = resp.json()
    assert data["greeting"]["greeting"] == "Good morning"


# ===========================================================================
# Gap 16: memory.py — search with content fallback, entities empty search, entity_type filter
# Lines: 129-130, 170, 186
# ===========================================================================


async def test_memory_search_content_fallback():
    """POST /memory/search with no summary uses content[:200] (lines 129-130)."""
    from src.app.api.routes.memory import router

    mock_rows = [
        {
            "id": uuid.uuid4(),
            "summary": "",  # empty summary
            "content": "This is a long content entry that should be used as fallback.",
            "rank": 0.5,
        },
    ]

    mock_session = AsyncMock()
    app = _app_with_session(router, mock_session, prefix="/api/memory")

    with patch(
        "src.app.api.routes.memory.search_episodes_bm25",
        new_callable=AsyncMock,
        return_value=mock_rows,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/memory/search", json={"query": "test"})

    assert resp.status_code == 200
    data = resp.json()
    # The answer should contain the content since summary is empty
    assert "This is a long content" in data["answer"]


async def test_memory_entities_search_empty_results():
    """GET /memory/entities?search=xyz returns empty when no entity IDs match (line 170)."""
    from src.app.api.routes.memory import router

    mock_session = AsyncMock()
    app = _app_with_session(router, mock_session, prefix="/api/memory")

    with patch(
        "src.app.api.routes.memory.search_entities",
        new_callable=AsyncMock,
        return_value=[],  # No matching entities
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/memory/entities", params={"search": "nonexistent"})

    assert resp.status_code == 200
    data = resp.json()
    assert data == []


async def test_memory_entities_with_type_filter():
    """GET /memory/entities?entity_type=person exercises type filter (line 186)."""
    from src.app.api.routes.memory import router

    now = datetime.now(UTC)
    mock_entity = MagicMock()
    mock_entity.id = uuid.uuid4()
    mock_entity.name = "Alice"
    mock_entity.entity_type = "person"
    mock_entity.canonical_name = None
    mock_entity.mention_count = 3
    mock_entity.first_seen = now
    mock_entity.last_seen = now
    mock_entity.metadata_ = {}
    mock_entity.created_at = now

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_entity]
    mock_session.execute = AsyncMock(return_value=mock_result)

    app = _app_with_session(router, mock_session, prefix="/api/memory")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/memory/entities", params={"entity_type": "person"})

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["entity_type"] == "person"


# ===========================================================================
# Gap 28: habits.py — _fmt_dt returning None (line 83)
# ===========================================================================


async def test_habits_fmt_dt_returns_none():
    """_fmt_dt returns None when given None (line 83)."""
    from src.app.api.routes.habits import _fmt_dt

    assert _fmt_dt(None) is None


async def test_habits_fmt_dt_returns_iso():
    """_fmt_dt returns ISO string for a valid datetime."""
    from src.app.api.routes.habits import _fmt_dt

    dt = datetime(2026, 3, 16, 12, 0, 0, tzinfo=UTC)
    assert _fmt_dt(dt) == dt.isoformat()


async def test_habits_dto_with_none_last_completed():
    """HabitDTO created from habit with last_completed_at=None uses _fmt_dt None path."""
    from src.app.api.routes.habits import _habit_to_dto

    mock_habit = MagicMock()
    mock_habit.id = uuid.uuid4()
    mock_habit.name = "Read"
    mock_habit.description = None
    mock_habit.frequency = "daily"
    mock_habit.frequency_days = 1
    mock_habit.current_streak = 0
    mock_habit.longest_streak = 0
    mock_habit.total_completions = 0
    mock_habit.last_completed_at = None  # This triggers _fmt_dt(None) -> None
    mock_habit.active = True
    mock_habit.tags = []
    mock_habit.created_at = datetime.now(UTC)

    dto = _habit_to_dto(mock_habit)
    assert dto.last_completed_at is None

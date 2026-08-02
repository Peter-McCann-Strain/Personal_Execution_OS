"""Transport, parsing, timeout, and secret-hygiene tests for GitHubClient."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.app.core.github_client import GitHubClient, Issue, _parse_issue


def _response(
    *,
    status: int = 200,
    payload: object | None = None,
    json_error: Exception | None = None,
    text: str = "",
) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.text = text
    if json_error is not None:
        response.json.side_effect = json_error
    else:
        response.json.return_value = payload
    return response


def _async_client(
    method: str,
    *,
    response: MagicMock | None = None,
    error: Exception | None = None,
) -> tuple[MagicMock, AsyncMock]:
    client = MagicMock()
    request_mock = AsyncMock()
    if error is not None:
        request_mock.side_effect = error
    else:
        request_mock.return_value = response
    setattr(client, method, request_mock)

    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)
    constructor = MagicMock(return_value=context)
    return constructor, request_mock


def _issue_payload(**overrides: object) -> dict[str, object]:
    return {
        "number": overrides.get("number", 17),
        "html_url": overrides.get(
            "html_url",
            "https://github.example/owner/repo/issues/17",
        ),
        "state": overrides.get("state", "open"),
        "title": overrides.get("title", "Production alert"),
        "labels": overrides.get(
            "labels",
            [
                {"name": "incident"},
                {"name": 42},
                "fingerprint:abc",
                7,
            ],
        ),
    }


def test_issue_parser_handles_api_shapes_defaults_and_state_properties() -> None:
    payload = _issue_payload()
    issue = _parse_issue(payload)

    assert issue.number == 17
    assert issue.url.endswith("/issues/17")
    assert issue.title == "Production alert"
    assert issue.labels == ["incident", "fingerprint:abc"]
    assert issue.raw is payload
    assert issue.is_open is True
    assert issue.is_closed is False

    defaulted = _parse_issue({})
    assert defaulted == Issue(
        number=0,
        url="",
        state="open",
        title="",
        labels=[],
        raw={},
    )
    closed = _parse_issue(_issue_payload(state="closed", labels=None))
    assert closed.is_open is False
    assert closed.is_closed is True


@pytest.mark.asyncio
async def test_unconfigured_client_is_a_network_free_noop() -> None:
    missing_token = GitHubClient(token="", repo="owner/repo")
    invalid_repo = GitHubClient(token="token", repo="owner-only")
    assert missing_token.configured is False
    assert invalid_repo.configured is False

    with patch("src.app.core.github_client.httpx.AsyncClient") as constructor:
        assert await missing_token.find_issue_by_fingerprint("abc") is None
        assert await missing_token.create_issue(title="Title", body="Body", labels=[]) is None
        assert await missing_token.comment_on_issue(issue_number=1, body="Comment") is False
        assert await missing_token.set_labels(issue_number=1, labels=["incident"]) is False
        assert await missing_token.close_issue(issue_number=1) is False
    constructor.assert_not_called()


@pytest.mark.asyncio
async def test_search_normalizes_repo_and_returns_first_non_pull_request_issue() -> None:
    client = GitHubClient(
        token="secret-token",
        repo=" /owner/repo/ ",
        timeout=3.5,
    )
    response = _response(
        payload=[
            {"number": 1, "pull_request": {}},
            "unexpected",
            _issue_payload(),
        ],
    )
    constructor, get_mock = _async_client("get", response=response)

    with patch(
        "src.app.core.github_client.httpx.AsyncClient",
        constructor,
    ):
        result = await client.find_issue_by_fingerprint("abc")

    assert result is not None
    assert result.number == 17
    constructor.assert_called_once_with(timeout=3.5)
    get_mock.assert_awaited_once_with(
        "https://api.github.com/repos/owner/repo/issues",
        headers={
            "Authorization": "Bearer secret-token",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "personal-execution-os-issue-filer",
        },
        params={
            "labels": "fingerprint:abc",
            "state": "all",
            "per_page": "1",
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "expected_event"),
    [
        (_response(status=403, payload={"secret": "body-secret"}), "non2xx"),
        (_response(json_error=ValueError("bad json")), "bad_json"),
        (_response(payload={"items": []}), "non_list"),
        (_response(payload=[]), "empty"),
        (_response(payload=[{"pull_request": {}}]), "pull_request_only"),
    ],
)
async def test_search_rejects_error_and_unexpected_response_bodies(
    response: MagicMock,
    expected_event: str,
) -> None:
    client = GitHubClient(token="token-must-not-log", repo="owner/repo")
    constructor, _ = _async_client("get", response=response)

    with (
        patch("src.app.core.github_client.httpx.AsyncClient", constructor),
        patch("src.app.core.github_client.logger.warning") as warning,
    ):
        assert await client.find_issue_by_fingerprint("abc") is None

    if expected_event in {"non2xx", "bad_json"}:
        warning.assert_called_once()
    else:
        warning.assert_not_called()
    logged = repr(warning.call_args_list)
    assert "token-must-not-log" not in logged
    assert "body-secret" not in logged
    if expected_event == "non2xx":
        response.json.assert_not_called()


@pytest.mark.asyncio
async def test_search_timeout_degrades_without_logging_token() -> None:
    client = GitHubClient(token="timeout-secret-token", repo="owner/repo")
    request = httpx.Request("GET", "https://api.github.com")
    timeout = httpx.ReadTimeout("request timed out", request=request)
    constructor, _ = _async_client("get", error=timeout)

    with (
        patch("src.app.core.github_client.httpx.AsyncClient", constructor),
        patch("src.app.core.github_client.logger.warning") as warning,
    ):
        assert await client.find_issue_by_fingerprint("abc") is None

    warning.assert_called_once()
    assert warning.call_args.args[0] == "github_client_search_failed"
    assert warning.call_args.kwargs["error"] == "request timed out"
    assert "timeout-secret-token" not in repr(warning.call_args)


@pytest.mark.asyncio
async def test_create_issue_posts_exact_body_and_parses_success() -> None:
    client = GitHubClient(token="token", repo="owner/repo")
    response = _response(status=201, payload=_issue_payload(number=22))
    constructor, post_mock = _async_client("post", response=response)

    with patch("src.app.core.github_client.httpx.AsyncClient", constructor):
        result = await client.create_issue(
            title="Alert",
            body="Evidence",
            labels=["incident", "count:1"],
        )

    assert result is not None
    assert result.number == 22
    post_mock.assert_awaited_once()
    assert post_mock.await_args.args[0].endswith("/owner/repo/issues")
    assert post_mock.await_args.kwargs["json"] == {
        "title": "Alert",
        "body": "Evidence",
        "labels": ["incident", "count:1"],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "error", "warning_event"),
    [
        (
            None,
            httpx.ConnectError(
                "connection failed",
                request=httpx.Request("POST", "https://api.github.com"),
            ),
            "github_client_create_failed",
        ),
        (
            _response(
                status=422,
                payload={"message": "validation", "token": "response-secret"},
            ),
            None,
            "github_client_create_non2xx",
        ),
        (
            _response(json_error=ValueError("bad json")),
            None,
            "github_client_create_bad_json",
        ),
    ],
)
async def test_create_issue_handles_transport_status_and_json_failures_without_secrets(
    response: MagicMock | None,
    error: Exception | None,
    warning_event: str,
) -> None:
    client = GitHubClient(token="create-secret-token", repo="owner/repo")
    constructor, _ = _async_client("post", response=response, error=error)

    with (
        patch("src.app.core.github_client.httpx.AsyncClient", constructor),
        patch("src.app.core.github_client.logger.warning") as warning,
    ):
        assert await client.create_issue(title="Alert", body="Body", labels=[]) is None

    warning.assert_called_once()
    assert warning.call_args.args[0] == warning_event
    logged = repr(warning.call_args)
    assert "create-secret-token" not in logged
    assert "response-secret" not in logged
    if response is not None and response.status_code >= 400:
        response.json.assert_not_called()


@pytest.mark.asyncio
async def test_create_issue_rejects_non_object_success_payload() -> None:
    client = GitHubClient(token="token", repo="owner/repo")
    constructor, _ = _async_client("post", response=_response(payload=[]))
    with patch("src.app.core.github_client.httpx.AsyncClient", constructor):
        assert await client.create_issue(title="Alert", body="Body", labels=[]) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "error", "expected"),
    [
        (201, None, True),
        (429, None, False),
        (
            0,
            httpx.ReadTimeout(
                "comment timeout",
                request=httpx.Request("POST", "https://api.github.com"),
            ),
            False,
        ),
    ],
)
async def test_comment_covers_success_non2xx_and_timeout(
    status: int,
    error: Exception | None,
    expected: bool,
) -> None:
    client = GitHubClient(token="token", repo="owner/repo")
    constructor, post_mock = _async_client(
        "post",
        response=_response(status=status),
        error=error,
    )
    with patch("src.app.core.github_client.httpx.AsyncClient", constructor):
        assert await client.comment_on_issue(issue_number=9, body="Recurrence") is expected
    post_mock.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "error", "expected"),
    [
        (200, None, True),
        (500, None, False),
        (
            0,
            httpx.ConnectError(
                "labels unavailable",
                request=httpx.Request("PUT", "https://api.github.com"),
            ),
            False,
        ),
    ],
)
async def test_set_labels_covers_success_non2xx_and_transport_failure(
    status: int,
    error: Exception | None,
    expected: bool,
) -> None:
    client = GitHubClient(token="token", repo="owner/repo")
    constructor, put_mock = _async_client(
        "put",
        response=_response(status=status),
        error=error,
    )
    with patch("src.app.core.github_client.httpx.AsyncClient", constructor):
        assert (
            await client.set_labels(
                issue_number=9,
                labels=["incident", "count:2"],
            )
            is expected
        )
    put_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_with_comment_posts_comment_then_patches_closed_state() -> None:
    client = GitHubClient(token="token", repo="owner/repo")
    constructor, patch_mock = _async_client(
        "patch",
        response=_response(status=200),
    )
    with (
        patch("src.app.core.github_client.httpx.AsyncClient", constructor),
        patch.object(
            client,
            "comment_on_issue",
            new=AsyncMock(return_value=False),
        ) as comment_mock,
    ):
        assert await client.close_issue(issue_number=9, comment="Recovered") is True

    comment_mock.assert_awaited_once_with(issue_number=9, body="Recovered")
    assert patch_mock.await_args.args[0].endswith("/issues/9")
    assert patch_mock.await_args.kwargs["json"] == {"state": "closed"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "error"),
    [
        (503, None),
        (
            0,
            httpx.ReadTimeout(
                "close timeout",
                request=httpx.Request("PATCH", "https://api.github.com"),
            ),
        ),
    ],
)
async def test_close_covers_non2xx_and_timeout_without_optional_comment(
    status: int,
    error: Exception | None,
) -> None:
    client = GitHubClient(token="token", repo="owner/repo")
    constructor, patch_mock = _async_client(
        "patch",
        response=_response(status=status),
        error=error,
    )
    with (
        patch("src.app.core.github_client.httpx.AsyncClient", constructor),
        patch.object(client, "comment_on_issue", new=AsyncMock()) as comment_mock,
    ):
        assert await client.close_issue(issue_number=9) is False
    comment_mock.assert_not_awaited()
    patch_mock.assert_awaited_once()

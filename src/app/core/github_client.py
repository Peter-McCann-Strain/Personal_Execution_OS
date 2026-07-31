"""Thin async wrapper around the GitHub REST API for issue filing (P3.9).

Used exclusively by :mod:`src.app.workers.github_filer` to open / comment on
/ close issues representing live production incidents. Kept deliberately
small — four verbs (search-by-fingerprint, create, comment, close) is
all the filer needs. If we ever need more of the GitHub surface we'll
pull in PyGithub proper; for now an ``httpx.AsyncClient`` keeps the
dependency footprint flat.

Authentication:
    Uses ``settings.github_token`` (SecretStr). When unset the client is
    **unconfigured** and every method returns ``None`` / a no-op result
    without raising. This is the single invariant the filer relies on to
    keep alerts flowing when GitHub is down or unconfigured.

Error handling:
    All HTTP errors are converted into ``None`` returns and a structlog
    warning. The alert pipeline MUST keep running even if GitHub is
    rate-limited, returning 5xx, or the token was revoked. "Silent
    degradation" is a deliberate design choice for this specific helper
    because it's a *secondary* output — Telegram is the primary fan-out
    and is wired separately.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

_GITHUB_API_ROOT = "https://api.github.com"
_DEFAULT_TIMEOUT_SECONDS = 10.0
_DEFAULT_API_VERSION = "2022-11-28"


@dataclass(frozen=True)
class Issue:
    """A minimal GitHub issue representation for the filer.

    Only the fields the filer actually reads are captured. The raw JSON
    payload from GitHub is attached as ``raw`` for callers that need more
    context (diagnostic logging, richer dedup).
    """

    number: int
    url: str  # ``html_url`` — the one users open in a browser
    state: str  # "open" | "closed"
    title: str
    labels: list[str]
    raw: dict[str, Any]

    @property
    def is_open(self) -> bool:
        return self.state == "open"

    @property
    def is_closed(self) -> bool:
        return self.state == "closed"


def _parse_issue(payload: dict[str, Any]) -> Issue:
    """Translate a GitHub issue JSON blob into the flat :class:`Issue` dataclass."""
    labels_raw = payload.get("labels") or []
    labels: list[str] = []
    for label in labels_raw:
        # The API returns labels as objects in the modern REST v3 surface,
        # but the search endpoint can return bare strings for a tight-fit
        # response. Handle both shapes defensively.
        if isinstance(label, dict):
            name = label.get("name")
            if isinstance(name, str):
                labels.append(name)
        elif isinstance(label, str):
            labels.append(label)
    return Issue(
        number=int(payload.get("number", 0)),
        url=str(payload.get("html_url", "")),
        state=str(payload.get("state", "open")),
        title=str(payload.get("title", "")),
        labels=labels,
        raw=payload,
    )


class GitHubClient:
    """Async HTTP client for the subset of GitHub endpoints the filer uses.

    Instantiated per-call from the filer — the overhead of an httpx client
    is a single TCP connection and is dwarfed by the round-trip latency
    of a GitHub API request. Using a short-lived client keeps the worker
    simple (no shared state, no connection-pool lifecycle) at the cost of
    a negligible per-call handshake.
    """

    def __init__(
        self,
        *,
        token: str,
        repo: str,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """Configure the client. ``repo`` is ``owner/name`` (e.g. ``foo/bar``)."""
        self._token = token
        self._repo = repo.strip().strip("/")
        self._timeout = timeout

    @property
    def configured(self) -> bool:
        """True iff both a token and a ``owner/repo`` string are present."""
        return bool(self._token) and "/" in self._repo

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": _DEFAULT_API_VERSION,
            "User-Agent": "personal-execution-os-issue-filer",
        }

    async def find_issue_by_fingerprint(self, fingerprint: str) -> Issue | None:
        """Return the first open OR closed issue tagged ``fingerprint:<fp>``.

        We want to find both states: an open issue means this is a
        recurrence (comment + counter bump); a *closed* issue means a
        human resolved a prior occurrence (the dedup row should be wiped
        so a new recurrence opens a fresh issue). Returning the first
        match is fine — fingerprints are unique by construction.
        """
        if not self.configured:
            return None
        label = f"fingerprint:{fingerprint}"
        params = {
            "labels": label,
            "state": "all",
            "per_page": "1",
        }
        url = f"{_GITHUB_API_ROOT}/repos/{self._repo}/issues"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url, headers=self._headers(), params=params)
        except httpx.HTTPError as exc:
            logger.warning(
                "github_client_search_failed",
                repo=self._repo,
                error=str(exc),
                fingerprint=fingerprint,
            )
            return None

        if response.status_code >= 400:
            logger.warning(
                "github_client_search_non2xx",
                status=response.status_code,
                repo=self._repo,
                fingerprint=fingerprint,
            )
            return None

        try:
            payload = response.json()
        except ValueError:
            logger.warning(
                "github_client_search_bad_json",
                status=response.status_code,
                repo=self._repo,
            )
            return None

        if not isinstance(payload, list) or not payload:
            return None
        # GitHub returns PRs under the same issues endpoint — skip them. They
        # carry a ``pull_request`` key which issues never have.
        for item in payload:
            if isinstance(item, dict) and "pull_request" not in item:
                return _parse_issue(item)
        return None

    async def create_issue(
        self,
        *,
        title: str,
        body: str,
        labels: list[str],
    ) -> Issue | None:
        """POST a new issue to the configured repo; return ``None`` on failure."""
        if not self.configured:
            return None
        url = f"{_GITHUB_API_ROOT}/repos/{self._repo}/issues"
        data: dict[str, Any] = {
            "title": title,
            "body": body,
            "labels": labels,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, headers=self._headers(), json=data)
        except httpx.HTTPError as exc:
            logger.warning(
                "github_client_create_failed",
                repo=self._repo,
                error=str(exc),
            )
            return None

        if response.status_code >= 400:
            logger.warning(
                "github_client_create_non2xx",
                status=response.status_code,
                repo=self._repo,
            )
            return None

        try:
            payload = response.json()
        except ValueError:
            logger.warning("github_client_create_bad_json", repo=self._repo)
            return None
        if not isinstance(payload, dict):
            return None
        return _parse_issue(payload)

    async def comment_on_issue(
        self,
        *,
        issue_number: int,
        body: str,
    ) -> bool:
        """Post a comment. Returns True on 2xx, False otherwise."""
        if not self.configured:
            return False
        url = f"{_GITHUB_API_ROOT}/repos/{self._repo}/issues/{issue_number}/comments"
        data = {"body": body}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, headers=self._headers(), json=data)
        except httpx.HTTPError as exc:
            logger.warning(
                "github_client_comment_failed",
                repo=self._repo,
                issue=issue_number,
                error=str(exc),
            )
            return False
        if response.status_code >= 400:
            logger.warning(
                "github_client_comment_non2xx",
                status=response.status_code,
                repo=self._repo,
                issue=issue_number,
            )
            return False
        return True

    async def set_labels(
        self,
        *,
        issue_number: int,
        labels: list[str],
    ) -> bool:
        """Replace the full label set on an issue. Used to bump ``count:<N>``."""
        if not self.configured:
            return False
        url = f"{_GITHUB_API_ROOT}/repos/{self._repo}/issues/{issue_number}/labels"
        data = {"labels": labels}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.put(url, headers=self._headers(), json=data)
        except httpx.HTTPError as exc:
            logger.warning(
                "github_client_set_labels_failed",
                repo=self._repo,
                issue=issue_number,
                error=str(exc),
            )
            return False
        if response.status_code >= 400:
            logger.warning(
                "github_client_set_labels_non2xx",
                status=response.status_code,
                repo=self._repo,
                issue=issue_number,
            )
            return False
        return True

    async def close_issue(
        self,
        *,
        issue_number: int,
        comment: str | None = None,
    ) -> bool:
        """Close an issue with an optional closing comment."""
        if not self.configured:
            return False
        if comment:
            await self.comment_on_issue(issue_number=issue_number, body=comment)
        url = f"{_GITHUB_API_ROOT}/repos/{self._repo}/issues/{issue_number}"
        data = {"state": "closed"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.patch(url, headers=self._headers(), json=data)
        except httpx.HTTPError as exc:
            logger.warning(
                "github_client_close_failed",
                repo=self._repo,
                issue=issue_number,
                error=str(exc),
            )
            return False
        if response.status_code >= 400:
            logger.warning(
                "github_client_close_non2xx",
                status=response.status_code,
                repo=self._repo,
                issue=issue_number,
            )
            return False
        return True


__all__ = [
    "GitHubClient",
    "Issue",
]

"""Shared GitHub issue filer for alert workers (P3.9).

The six alert workers (DLQ, schema-drift, quality, quality-gates, SLO
burn-rate, cost-ceiling) each fan an alert out to Telegram. This module
adds a secondary fan-out to GitHub — one issue per distinct alert
fingerprint, deduplicated across runs, with comments + counter-label
bumps on recurrence.

The design principle: **Telegram is the fast path, GitHub is the
durable backlog.** If GitHub is unconfigured, rate-limited, or returning
5xx, the alert pipeline MUST keep running. Every code path in this
module is therefore wrapped in a broad try/except that logs at WARNING
and returns a sentinel value — it never re-raises into the caller.

Fingerprinting:
    ``sha256((category, *sorted_key_fields))`` — deterministic across
    runs so the same crash on Monday and Thursday maps to the same
    issue. Keys are sorted to avoid order-dependent hashes when callers
    build the key_fields dict.

Dedup table:
    :class:`src.app.persistence.models.IssueDedup` (UNIQUE on
    fingerprint). Inserted on first occurrence; UPDATE
    recurrence_count+1 + last_seen on recurrence.

Severity mapping (category → p{0,1,2}):
    * cost_ceiling → p0  (spend is ON FIRE, stop spending NOW)
    * dlq, schema_drift → p1  (real failures, not transient)
    * slo_burn, cost_rolling → p1  (SLO breach or projected overrun)
    * quality, quality_gates, eval_ceiling → p2  (degradation, investigate)
    * Default → p2

Area mapping (category → area-{db,llm,worker,mcp,eval,misc}):
    Heuristic based on category. Override explicitly by passing
    ``alert.area`` on the AlertRecord.

Safety invariant:
    :func:`redact` is applied to every piece of free text that could
    carry user content (traceback, log lines, raw DB errors) before the
    text goes into the issue body. A user message, email, phone, or
    postcode must NEVER reach GitHub (which is a third party).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import delete, select, update

from src.app.config import Settings
from src.app.core.github_client import GitHubClient, Issue
from src.app.core.pii_redactor import redact
from src.app.persistence.models import IssueDedup

logger = structlog.get_logger()


# Severity mapping — exposed for the tests and for the filer logic.
_CATEGORY_SEVERITY: dict[str, str] = {
    "cost_ceiling": "p0",
    "dlq": "p1",
    "schema_drift": "p1",
    "slo_burn": "p1",
    "cost_rolling": "p1",
    "quality": "p2",
    "quality_gates": "p2",
    "eval_ceiling": "p2",
}

# Category → area-label mapping. Heuristic only — callers may override by
# setting ``AlertRecord.area`` explicitly (e.g. a DLQ failure from the MCP
# bridge would want ``area=mcp``).
_CATEGORY_AREA: dict[str, str] = {
    "dlq": "worker",
    "schema_drift": "db",
    "quality": "eval",
    "quality_gates": "eval",
    "slo_burn": "llm",
    "cost_ceiling": "llm",
    "cost_rolling": "llm",
    "eval_ceiling": "eval",
}


@dataclass(frozen=True)
class AlertRecord:
    """Structured description of a firing alert, ready to be filed.

    Callers (the six alert workers) populate this from their own context
    and pass it to :func:`file_github_issue`. Keeping the record as a
    frozen dataclass makes the fingerprint deterministic and simplifies
    unit tests.

    Fields:
        category: One of ``_CATEGORY_SEVERITY``'s keys (or a new string —
            maps to p2 / area-misc by default).
        title: Short, grep-friendly issue title (<= ~120 chars).
        summary: Human prose for the issue body's top section.
        key_fields: Dict used to build the fingerprint. Only keys +
            values from here are hashed — summary prose is excluded so
            cosmetic wording changes don't split an existing issue.
        context: Free-form body segments (traceback, log lines, metric
            readouts). Every string value is piped through PII redact
            before being rendered into the issue body.
        request_id / trace_id: Included as grep-friendly anchors in both
            the body and the recurrence comments.
        area: Optional explicit area override. Empty string → use the
            category → area heuristic.
    """

    category: str
    title: str
    summary: str
    key_fields: dict[str, Any] = field(default_factory=dict)
    context: dict[str, str] = field(default_factory=dict)
    request_id: str | None = None
    trace_id: str | None = None
    area: str = ""


def compute_fingerprint(category: str, key_fields: dict[str, Any]) -> str:
    """Return a stable sha256 hex digest for ``(category, key_fields)``.

    Keys are sorted so ``{"a":1,"b":2}`` and ``{"b":2,"a":1}`` hash the
    same; values are coerced to ``str(...)`` to sidestep JSON-ordering
    quirks. Truncated to 12 hex chars in the label for readability —
    the full digest is what we store in the DB.
    """
    hasher = hashlib.sha256()
    hasher.update(category.encode("utf-8"))
    for key in sorted(key_fields.keys()):
        hasher.update(b"\x00")
        hasher.update(str(key).encode("utf-8"))
        hasher.update(b"\x01")
        hasher.update(str(key_fields[key]).encode("utf-8"))
    return hasher.hexdigest()


def severity_for(category: str) -> str:
    """Map a category string to a ``p0|p1|p2`` severity label."""
    return _CATEGORY_SEVERITY.get(category, "p2")


def area_for(category: str, override: str = "") -> str:
    """Map a category string to an ``area-{db,llm,worker,mcp,eval,misc}`` label."""
    if override:
        return override
    return _CATEGORY_AREA.get(category, "misc")


def _labels_for(alert: AlertRecord, *, count: int) -> list[str]:
    """Assemble the canonical label set for an issue representing ``alert``."""
    severity = severity_for(alert.category)
    area = area_for(alert.category, alert.area)
    fingerprint = compute_fingerprint(alert.category, alert.key_fields)[:12]
    labels = [
        "from-prod",
        "bug",
        f"area-{area}",
        f"severity-{severity}",
        f"fingerprint:{fingerprint}",
    ]
    # Add a counter label so a quick glance at the issue list surfaces the
    # worst offenders. Kept as a label rather than a prose count so
    # filtering by ``count:>=10`` works via the GitHub UI.
    if count > 1:
        labels.append(f"count:{count}")
    return labels


def _render_body(alert: AlertRecord) -> str:
    """Render the initial issue body — summary + context + redacted traceback."""
    lines: list[str] = []
    lines.append(f"**Category:** `{alert.category}`")
    lines.append(f"**Severity:** `{severity_for(alert.category)}`")
    lines.append("")
    if alert.summary:
        lines.append(redact(alert.summary))
        lines.append("")

    if alert.key_fields:
        lines.append("## Key fields")
        for key in sorted(alert.key_fields.keys()):
            raw_val = alert.key_fields[key]
            # Redact strings; pass through non-strings (ints, bools, floats).
            value = redact(str(raw_val)) if isinstance(raw_val, str) else raw_val
            lines.append(f"- **{key}**: `{value}`")
        lines.append("")

    if alert.request_id or alert.trace_id:
        lines.append("## Correlation")
        if alert.request_id:
            lines.append(f"- request_id: `{alert.request_id}`")
        if alert.trace_id:
            lines.append(f"- trace_id: `{alert.trace_id}`")
        lines.append("")

    if alert.context:
        for section, body in alert.context.items():
            if not body:
                continue
            lines.append(f"## {section}")
            redacted = redact(body)
            # Use a fenced block for multi-line context (tracebacks, log lines).
            if "\n" in redacted:
                lines.append("```")
                lines.append(redacted)
                lines.append("```")
            else:
                lines.append(redacted)
            lines.append("")

    lines.append("---")
    lines.append(
        "_Filed automatically by the production alert pipeline "
        "(`src.app.workers.github_filer`). Recurrences will add a "
        "comment + bump the `count:<N>` label rather than spawn a "
        "duplicate issue. Close this issue when the underlying bug is "
        "fixed — the dedup row will be wiped so a future occurrence "
        "opens a fresh issue._"
    )
    return "\n".join(lines)


def _render_recurrence_comment(
    alert: AlertRecord,
    *,
    count: int,
    now: datetime,
) -> str:
    """Return the body of the comment posted when a known fingerprint recurs."""
    lines = [
        f"**Recurrence #{count}** at `{now.isoformat(timespec='seconds')}`",
    ]
    if alert.request_id:
        lines.append(f"- request_id: `{alert.request_id}`")
    if alert.trace_id:
        lines.append(f"- trace_id: `{alert.trace_id}`")
    if alert.summary:
        lines.append("")
        lines.append(redact(alert.summary))
    return "\n".join(lines)


def _build_client(settings: Settings) -> GitHubClient | None:
    """Instantiate a :class:`GitHubClient` iff the settings permit.

    Returns ``None`` (logged at DEBUG) if the filer is disabled or the
    token/repo pair is unset — the caller then short-circuits. This is
    the single place the no-op invariant is enforced.
    """
    if not bool(getattr(settings, "github_issue_filer_enabled", False)):
        logger.debug("github_filer_disabled")
        return None
    repo = str(getattr(settings, "github_issue_repo", "") or "").strip()
    token = settings.github_token.get_secret_value() if settings.github_token else ""
    if not repo or not token:
        logger.debug(
            "github_filer_unconfigured",
            has_repo=bool(repo),
            has_token=bool(token),
        )
        return None
    return GitHubClient(token=token, repo=repo)


async def file_github_issue(
    alert: AlertRecord,
    *,
    settings: Settings,
    session_factory: Any,
    client: GitHubClient | None = None,
    now: datetime | None = None,
) -> str | None:
    """File (or comment-on-recurrence) a GitHub issue for ``alert``.

    Returns the issue URL on success, ``None`` on any failure or no-op.
    Never raises — every failure path logs at WARNING and returns None
    so the alert worker's telegram send remains authoritative.

    ``client`` is injectable for testing; in prod the caller passes
    ``None`` and we build one from ``settings``. ``session_factory`` is
    the same async session factory the worker receives via ARQ context.
    """
    # --- Guard: filer must never raise into the caller ---------------------
    # Wrap the whole function body in a broad try/except below. The top-level
    # guard is structural (tested by "GitHub down → no exception" in the
    # test suite); finer-grained except handlers live on each HTTP call so
    # we can log at the right granularity.
    try:
        gh = client if client is not None else _build_client(settings)
        if gh is None:
            return None

        now_dt = now if now is not None else datetime.now(UTC)
        fingerprint = compute_fingerprint(alert.category, alert.key_fields)

        # --- Look up any existing issue for this fingerprint ---------------
        existing_issue: Issue | None = await gh.find_issue_by_fingerprint(fingerprint)

        async with session_factory() as session:
            row_stmt = select(IssueDedup).where(IssueDedup.fingerprint == fingerprint)
            row_result = await session.execute(row_stmt)
            row: IssueDedup | None = row_result.scalar_one_or_none()

            # --- Case A: Human closed a prior issue → wipe + re-open -------
            # If the remote issue is closed (presumably by a human fixing the
            # underlying bug), the dedup row is stale. Delete it so the rest
            # of this function treats the alert as a brand-new fingerprint
            # and files a fresh issue.
            if existing_issue is not None and existing_issue.is_closed:
                if row is not None:
                    await session.execute(delete(IssueDedup).where(IssueDedup.id == row.id))
                    await session.commit()
                    row = None
                existing_issue = None

            # --- Case B: Known fingerprint, open issue → comment + bump ----
            if existing_issue is not None and row is not None:
                new_count = int(row.recurrence_count or 1) + 1
                comment_body = _render_recurrence_comment(alert, count=new_count, now=now_dt)
                await gh.comment_on_issue(
                    issue_number=existing_issue.number,
                    body=comment_body,
                )
                # Replace the full label set so ``count:<old>`` is removed and
                # ``count:<new>`` takes its place. Any human-added labels
                # will be lost — that's an acceptable trade-off for an
                # automation-owned issue.
                await gh.set_labels(
                    issue_number=existing_issue.number,
                    labels=_labels_for(alert, count=new_count),
                )
                await session.execute(
                    update(IssueDedup)
                    .where(IssueDedup.id == row.id)
                    .values(
                        recurrence_count=new_count,
                        last_seen=now_dt,
                    )
                )
                await session.commit()
                logger.info(
                    "github_filer_recurrence",
                    category=alert.category,
                    fingerprint=fingerprint,
                    recurrence_count=new_count,
                    issue_url=existing_issue.url,
                )
                return existing_issue.url

            # --- Case C: New fingerprint → create fresh issue --------------
            labels = _labels_for(alert, count=1)
            body = _render_body(alert)
            created = await gh.create_issue(
                title=alert.title,
                body=body,
                labels=labels,
            )
            if created is None:
                # Creation failed; leave the dedup table untouched so the next
                # alert run will retry. Still return None so the caller
                # (Telegram path) isn't blocked.
                logger.warning(
                    "github_filer_create_failed",
                    category=alert.category,
                    fingerprint=fingerprint,
                )
                return None

            new_row = IssueDedup(
                fingerprint=fingerprint,
                github_issue_number=created.number,
                github_issue_url=created.url,
                category=alert.category,
                first_seen=now_dt,
                last_seen=now_dt,
                recurrence_count=1,
            )
            session.add(new_row)
            await session.commit()
            logger.info(
                "github_filer_created",
                category=alert.category,
                fingerprint=fingerprint,
                issue_number=created.number,
                issue_url=created.url,
            )
            return created.url
    except Exception:
        # Last-resort guard: anything we missed above must NOT propagate.
        # Telegram is the fast path and is already sent by the time we run.
        logger.exception(
            "github_filer_unexpected_error",
            category=alert.category,
        )
        return None


# ---------------------------------------------------------------------------
# Auto-resolve cron (runs user-local 06:15)
# ---------------------------------------------------------------------------


async def run_github_issue_sync(ctx: dict) -> None:
    """Nightly sync — close idle issues + wipe rows for human-closed issues.

    Two passes per run:

    1. For each ``issue_dedup`` row with ``last_seen < now - N days`` AND
       ``resolved_at IS NULL``: comment + close the GitHub issue, set
       ``resolved_at = now()``.
    2. For each remaining row whose remote issue is already closed by a
       human: delete the row so a future recurrence opens a fresh
       issue.

    Safe to run while alerts are firing — the filer reads rows by
    fingerprint + commits in a separate transaction, so interleaving
    with the sync is fine.
    """
    settings: Settings = ctx["settings"]
    session_factory = ctx.get("session_factory")
    if session_factory is None:
        logger.warning("github_issue_sync_no_session_factory")
        return

    gh = _build_client(settings)
    if gh is None:
        return

    window_days = int(getattr(settings, "github_issue_dedup_window_days", 7))
    now_dt = datetime.now(UTC)
    cutoff = now_dt - timedelta(days=window_days)

    closed_count = 0
    wiped_count = 0

    async with session_factory() as session:
        # --- Pass 1: auto-close idle rows ---------------------------------
        stmt = (
            select(IssueDedup)
            .where(IssueDedup.resolved_at.is_(None))
            .where(IssueDedup.last_seen < cutoff)
        )
        stale_rows = list((await session.execute(stmt)).scalars().all())

        for row in stale_rows:
            if row.github_issue_number is None:
                continue
            comment = (
                f"No recurrence in {window_days}d — auto-resolving. "
                "Reopen manually if it happens again."
            )
            closed_ok = await gh.close_issue(
                issue_number=row.github_issue_number,
                comment=comment,
            )
            if closed_ok:
                await session.execute(
                    update(IssueDedup).where(IssueDedup.id == row.id).values(resolved_at=now_dt)
                )
                closed_count += 1

        # --- Pass 2: wipe rows whose GitHub issue was human-closed --------
        # Scan all still-unresolved rows (plus the just-resolved ones above
        # that belong in pass 1 are already gone). We deliberately re-read
        # so rows auto-closed above are not re-inspected.
        remaining_stmt = select(IssueDedup).where(IssueDedup.resolved_at.is_(None))
        remaining_rows = list((await session.execute(remaining_stmt)).scalars().all())
        for row in remaining_rows:
            if row.github_issue_number is None:
                continue
            issue = await gh.find_issue_by_fingerprint(row.fingerprint)
            # Match by number AND closed state — find_issue_by_fingerprint
            # returns the newest labelled issue, which may or may not be
            # the one we created. Comparing numbers is the safe move.
            if issue is not None and issue.is_closed and issue.number == row.github_issue_number:
                await session.execute(delete(IssueDedup).where(IssueDedup.id == row.id))
                wiped_count += 1

        await session.commit()

    logger.info(
        "github_issue_sync_done",
        closed=closed_count,
        wiped=wiped_count,
        window_days=window_days,
    )


__all__ = [
    "AlertRecord",
    "area_for",
    "compute_fingerprint",
    "file_github_issue",
    "run_github_issue_sync",
    "severity_for",
]

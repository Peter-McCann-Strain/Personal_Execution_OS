"""Research handler — multi-step web research with Tavily."""

from __future__ import annotations

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agents.specialists.research import run_research
from src.app.agents.tools.web_search import TavilySearch
from src.app.config import get_settings
from src.app.domain.constants import EpisodeType, ParaCategory
from src.app.domain.models import ArtifactRecord, ChatResponse, Intent, MessageInput
from src.app.domain.services.handlers._common import (
    enqueue_entity_extraction,
    enqueue_reflection_pack_refresh,
)
from src.app.persistence.repositories.episodes import create_episode
from src.app.persistence.repositories.runtime_records import create_artifact_record

logger = structlog.get_logger()


def _coerce_safety_flags(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [flag for flag in value if isinstance(flag, str) and flag]


def _build_research_citations(report: object) -> list[dict[str, str]]:
    findings = getattr(report, "findings", None)
    if not isinstance(findings, list):
        return []

    citations: list[dict[str, str]] = []
    for index, finding in enumerate(findings):
        source = getattr(finding, "source", None)
        if not isinstance(source, str) or not source.strip():
            continue
        key_points = getattr(finding, "key_points", None)
        excerpt = None
        if isinstance(key_points, list):
            excerpt = next(
                (point for point in key_points if isinstance(point, str) and point),
                None,
            )
        citations.append(
            {
                "source_id": source.strip(),
                "source_type": "web_result",
                "label": source.strip(),
                "excerpt": excerpt or "",
                "timestamp": f"finding-{index}",
            }
        )
    return citations


def _build_research_content_blocks(report: object) -> list[dict[str, object]]:
    blocks: list[dict[str, object]] = []

    synthesis = getattr(report, "synthesis", None)
    if isinstance(synthesis, str) and synthesis.strip():
        blocks.append({"type": "text", "text": synthesis.strip()})

    findings = getattr(report, "findings", None)
    if isinstance(findings, list) and findings:
        source_items = [_format_research_finding(finding) for finding in findings]
        source_items = [item for item in source_items if item]
        if source_items:
            blocks.append(
                {
                    "type": "bullet_list",
                    "title": f"Sources ({len(source_items)})",
                    "items": source_items,
                }
            )

    decision_framework = getattr(report, "decision_framework", None)
    options = getattr(decision_framework, "options", None)
    if isinstance(options, list) and options:
        decision_items = [_format_decision_option(option) for option in options]
        decision_items = [item for item in decision_items if item]
        if decision_items:
            blocks.append(
                {
                    "type": "bullet_list",
                    "title": "Decision framework",
                    "items": decision_items,
                }
            )

    recommendation = getattr(decision_framework, "recommendation", None)
    if isinstance(recommendation, str) and recommendation.strip():
        blocks.append(
            {
                "type": "field",
                "title": "Recommendation",
                "text": recommendation.strip(),
            }
        )

    if blocks:
        return blocks

    title = getattr(report, "title", None)
    if isinstance(title, str) and title.strip():
        return [{"type": "text", "text": title.strip()}]
    return []


def _format_research_finding(finding: object) -> str:
    source = getattr(finding, "source", None)
    source_text = source.strip() if isinstance(source, str) else ""
    key_points = getattr(finding, "key_points", None)
    points = (
        [point.strip() for point in key_points if isinstance(point, str) and point.strip()]
        if isinstance(key_points, list)
        else []
    )
    points_text = "; ".join(points)
    if source_text and points_text:
        return f"{source_text}: {points_text}"
    return source_text or points_text


def _format_decision_option(option: object) -> str:
    name = getattr(option, "name", None)
    name_text = name.strip() if isinstance(name, str) else ""
    pros = getattr(option, "pros", None)
    cons = getattr(option, "cons", None)
    pros_text = (
        ", ".join(item.strip() for item in pros if isinstance(item, str) and item.strip())
        if isinstance(pros, list)
        else ""
    )
    cons_text = (
        ", ".join(item.strip() for item in cons if isinstance(item, str) and item.strip())
        if isinstance(cons, list)
        else ""
    )
    if not name_text and not pros_text and not cons_text:
        return ""
    return f"{name_text or 'Option'} | Pros: {pros_text or 'none'} | Cons: {cons_text or 'none'}"


async def _persist_research_artifact(
    session: AsyncSession,
    *,
    user_id: str,
    episode_id: str,
    report: object,
    safety_flags: list[str],
    citations: list[dict[str, str]],
) -> None:
    payload = {
        "title": getattr(report, "title", ""),
        "search_queries": getattr(report, "search_queries", []),
        "finding_count": len(getattr(report, "findings", []) or []),
        "key_takeaway": getattr(report, "key_takeaway", None),
        "recommendation": (
            getattr(getattr(report, "decision_framework", None), "recommendation", None)
        ),
        "citations": citations,
        "safety_flags": safety_flags,
    }

    try:
        await create_artifact_record(
            session,
            user_id=user_id,
            artifact=ArtifactRecord(
                artifact_type="research_report",
                summary=str(getattr(report, "title", "Research report"))[:500],
                source_id=episode_id,
                payload=payload,
            ),
        )
        await session.commit()
    except Exception:
        logger.warning("research_artifact_persist_failed", exc_info=True)
        try:
            await session.rollback()
        except Exception:
            logger.warning("research_artifact_rollback_failed", exc_info=True)


async def handle_research(
    message: MessageInput,
    client: AsyncAnthropic,
    session: AsyncSession,
    _intent: Intent,
) -> ChatResponse:
    """Run the full research pipeline: generate queries, search, synthesise."""
    settings = get_settings()

    if not settings.tavily_configured:
        return ChatResponse(
            content=(
                "Research requires Tavily web search, but TAVILY_API_KEY is not configured. "
                "Please set it in your .env file to enable research capabilities."
            ),
            agent="research",
            metadata={"error": "tavily_not_configured"},
        )

    search_client = TavilySearch(api_key=settings.tavily_api_key.get_secret_value())

    try:
        report = await run_research(message.content, client, search_client)
    finally:
        await search_client.close()

    safety_flags = _coerce_safety_flags(getattr(report, "safety_flags", None))
    citations = _build_research_citations(report)
    content_blocks = _build_research_content_blocks(report)

    # Format the report for the user
    lines = [f"# {report.title}\n"]

    if report.synthesis:
        lines.append(report.synthesis)
        lines.append("")

    if report.findings:
        lines.append(f"**Sources ({len(report.findings)}):**")
        for finding in report.findings:
            key_pts = "; ".join(finding.key_points) if finding.key_points else ""
            lines.append(f"- {finding.source}: {key_pts}")
        lines.append("")

    if report.decision_framework:
        df = report.decision_framework
        if df.options:
            lines.append("**Decision Framework:**")
            for opt in df.options:
                pros = ", ".join(opt.pros) if opt.pros else "none"
                cons = ", ".join(opt.cons) if opt.cons else "none"
                lines.append(f"- **{opt.name}** | Pros: {pros} | Cons: {cons}")
        if df.recommendation:
            lines.append(f"\n**Recommendation:** {df.recommendation}")

    # Store the research episode
    episode = await create_episode(
        session,
        content=report.synthesis or report.title,
        summary=report.title,
        episode_type=EpisodeType.RESEARCH,
        source=message.source,
        para_category=ParaCategory.RESOURCE,
        tags=[],
        metadata={
            "search_queries": report.search_queries,
            "finding_count": len(report.findings),
            "safety_flags": safety_flags,
            "citations": citations,
        },
    )
    await session.commit()

    try:
        await enqueue_reflection_pack_refresh("episode_research_saved")
    except Exception as exc:
        logger.warning(
            "research_reflection_pack_refresh_degraded",
            episode_id=str(episode.id),
            error=str(exc),
            exc_info=True,
        )

    await _persist_research_artifact(
        session,
        user_id=message.user_id,
        episode_id=str(episode.id),
        report=report,
        safety_flags=safety_flags,
        citations=citations,
    )

    try:
        await enqueue_entity_extraction(
            episode_id=str(episode.id),
            text_content="\n".join(lines),
        )
    except Exception as exc:
        logger.warning(
            "research_entity_extraction_degraded",
            episode_id=str(episode.id),
            error=str(exc),
            exc_info=True,
        )

    return ChatResponse(
        content="\n".join(lines),
        agent="research",
        metadata={
            "episode_id": str(episode.id),
            "title": report.title,
            "search_queries": report.search_queries,
            "finding_count": len(report.findings),
            "safety_flags": safety_flags,
            "citations": citations,
            "content_blocks": content_blocks,
        },
    )

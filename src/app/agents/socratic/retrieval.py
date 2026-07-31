"""Second brain retrieval for Socratic tutorial Connector agent.

Queries notes, past tutorials, and episode embeddings to find relevant
prior work and knowledge for the Connector's preparation phase.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.persistence.repositories.notes import search_notes
from src.app.persistence.repositories.tutorials import get_past_tutorials

if TYPE_CHECKING:
    from src.app.core.embeddings import OllamaEmbeddings

logger = structlog.get_logger()


async def retrieve_second_brain_context(
    user_id: str,
    propositions: list[dict[str, Any]],
    submitted_work: str,
    db_session: AsyncSession,
    embeddings: OllamaEmbeddings | None = None,
) -> str:
    """Retrieve relevant notes and past tutorials for Connector preparation.

    Builds a context string from:
    1. Notes matching the submitted work's topics (full-text search)
    2. Past completed tutorials (for prior work links)

    Returns a formatted string for the second_brain_context parameter
    of prepare_connector(). Raises if retrieval fails.
    """
    _ = embeddings  # Reserved for Phase 2 vector search.
    context_parts: list[str] = []

    # Build a search query from propositions and submitted work
    query_terms = []
    for prop in propositions[:5]:  # Top 5 propositions
        if isinstance(prop, dict):
            query_terms.append(prop.get("text", ""))
    query = " ".join(query_terms)[:500] or submitted_work[:500]

    notes = await search_notes(db_session, query=query, limit=5)
    if notes:
        context_parts.append("## Relevant Notes from Second Brain")
        for note in notes:
            title = note.get("title", "Untitled")
            content = str(note.get("content", ""))[:300]
            created = note.get("created_at", "")
            context_parts.append(f"- **{title}** ({created}): {content}")

    past_tutorials = await get_past_tutorials(db_session, user_id=user_id, limit=5)
    if past_tutorials:
        context_parts.append("\n## Past Tutorial Sessions")
        for tut in past_tutorials:
            topic = getattr(tut, "topic", "Unknown topic")
            completed = getattr(tut, "completed_at", None)
            date_str = completed.isoformat() if completed else "unknown date"
            analysis = getattr(tut, "analysis", None) or {}
            gaps = analysis.get("knowledge_gaps", [])
            gap_str = (
                ", ".join(g.get("gap", str(g)) if isinstance(g, dict) else str(g) for g in gaps[:3])
                if gaps
                else "none identified"
            )
            context_parts.append(f"- **{topic}** ({date_str}) — Knowledge gaps: {gap_str}")

    if not context_parts:
        return ""

    return "\n".join(context_parts)

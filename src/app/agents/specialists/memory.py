"""Memory agent — semantic search, knowledge retrieval, and link discovery.

Uses Sonnet for retrieval synthesis and salvages plain-text answers when the
model misses the structured-output contract.
"""

from __future__ import annotations

import json
import re

import anthropic
import structlog
from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field

from src.app.agents.prompts.memory import ENTITY_SUMMARY_PROMPT, MEMORY_ANSWER_PROMPT
from src.app.config import get_settings
from src.app.core.exceptions import LLMError
from src.app.core.llm_helpers import call_and_extract_text, call_llm, extract_text

logger = structlog.get_logger()


class MemorySearchResult(BaseModel):
    content: str
    relevance_score: float = Field(ge=0.0, le=1.0)
    source_type: str  # "episode", "note", "entity"
    source_id: str


class MemoryAnswer(BaseModel):
    answer: str
    confidence: float = Field(ge=0.0, le=1.0)
    sources: list[MemorySearchResult] = Field(default_factory=list)
    follow_up_suggestions: list[str] = Field(default_factory=list)


async def answer_from_memory(
    query: str,
    context_chunks: list[dict],
    client: AsyncAnthropic,
    model: str | None = None,
    max_tokens: int | None = None,
) -> MemoryAnswer:
    """Answer a query using retrieved memory context.

    context_chunks: list of {"content": str, "score": float, "source_type": str,
                             "source_id": str}
    """
    settings = get_settings()
    model = model or settings.memory_model
    max_tokens = max_tokens or settings.memory_max_tokens

    if not context_chunks:
        return MemoryAnswer(
            answer="I don't have any relevant information stored about that.",
            confidence=0.0,
        )

    context_text = "\n\n---\n\n".join(
        f"[{c['source_type']}] (relevance: {c['score']:.2f})\n{c['content']}"
        for c in context_chunks
    )

    try:
        response = await call_llm(
            client,
            model=model,
            max_tokens=max_tokens,
            system=MEMORY_ANSWER_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (f"Question: {query}\n\nContext from memory:\n{context_text}"),
                }
            ],
        )
    except (anthropic.APIError, LLMError) as e:
        logger.error("Memory retrieval_failed", error=str(e), model=model)
        raise LLMError(f"Memory retrieval failed: {e}") from e

    raw = _strip_json_fences(extract_text(response).strip())
    try:
        return MemoryAnswer(**json.loads(raw))
    except (json.JSONDecodeError, ValueError):
        logger.warning(
            "memory_answer_parse_failed",
            model=model,
            raw_preview=raw[:400],
        )
        return _fallback_memory_answer(raw, context_chunks)


async def summarise_entity_context(
    entity_name: str,
    mentions: list[dict],
    client: AsyncAnthropic,
    model: str | None = None,
    max_tokens: int | None = None,
) -> str:
    """Summarise what we know about an entity from its mentions."""
    settings = get_settings()
    model = model or settings.memory_model
    max_tokens = max_tokens or settings.memory_summary_max_tokens

    if not mentions:
        return f"No information stored about {entity_name}."

    mentions_text = "\n".join(
        f"- [{m.get('date', 'unknown')}] {m.get('content', '')}" for m in mentions
    )

    return await call_and_extract_text(
        client,
        model=model,
        max_tokens=max_tokens,
        system=ENTITY_SUMMARY_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (f"Entity: {entity_name}\n\nMentions:\n{mentions_text}"),
            }
        ],
        error_context="Entity summary",
    )


def _strip_json_fences(text: str) -> str:
    """Remove optional markdown code fences around a JSON payload."""
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0]
    return text.strip()


def _fallback_memory_answer(raw_text: str, context_chunks: list[dict]) -> MemoryAnswer:
    """Salvage plain-text model output when structured parsing fails."""
    cleaned = _sanitize_fallback_text(raw_text.strip())
    if cleaned.startswith(("{", "[")):
        cleaned = (
            "I found relevant context, but I couldn't turn it into a clean answer. "
            "Ask again a bit more specifically and I'll try a narrower recall."
        )
    if not cleaned:
        cleaned = "I found related context, but I need a narrower question to answer it cleanly."

    top_chunks = context_chunks[:3]
    max_score = max((float(chunk.get("score", 0.0)) for chunk in top_chunks), default=0.0)
    confidence = min(max(max_score, 0.35), 0.8)

    return MemoryAnswer(
        answer=cleaned,
        confidence=confidence,
        sources=[
            MemorySearchResult(
                content=str(chunk.get("content", "")),
                relevance_score=min(max(float(chunk.get("score", 0.0)), 0.0), 1.0),
                source_type=str(chunk.get("source_type", "unknown")),
                source_id=str(chunk.get("source_id", "")),
            )
            for chunk in top_chunks
        ],
        follow_up_suggestions=[],
    )


def _sanitize_fallback_text(raw_text: str) -> str:
    """Drop leaked internal prefixes from plain-text fallback answers."""
    cleaned = " ".join(raw_text.split())
    cleaned = re.sub(r"(?is)failed to parse [^:\n]+ response:\s*", "", cleaned).strip()
    cleaned = re.sub(r"(?is)failed to parse [^:\n]+:\s*", "", cleaned).strip()
    cleaned = re.sub(r"(?is)(?:^|\s)sources\s*\(\d+\):\s*", " ", cleaned).strip()
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned

"""Pluggable context engine and inspection metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from src.app.core.context_budget import estimate_tokens
from src.app.core.context_manager import AssembledContext, assemble_context
from src.app.core.state_packet import packet_to_debug_dict, render_session_state_packet
from src.app.domain.models import SessionStatePacket

if False:  # pragma: no cover
    from anthropic import AsyncAnthropic


class DurableMemoryCandidate(BaseModel):
    """Potential long-lived memory detected before compaction."""

    model_config = ConfigDict(populate_by_name=True)

    category: str
    excerpt: str
    source_role: str = Field(serialization_alias="sourceRole")


class ContextSection(BaseModel):
    """Debug information for one context section."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    tokens: int
    item_count: int | None = Field(default=None, serialization_alias="itemCount")
    present: bool = True


class ContextInspection(BaseModel):
    """Operator-facing view of the assembled context."""

    model_config = ConfigDict(populate_by_name=True)

    engine: str = "hierarchical"
    history_summarized: bool = Field(serialization_alias="historySummarized")
    pruned_messages: int = Field(serialization_alias="prunedMessages")
    pruned_characters: int = Field(serialization_alias="prunedCharacters")
    durable_memory_candidates: list[DurableMemoryCandidate] = Field(
        default_factory=list,
        serialization_alias="durableMemoryCandidates",
    )
    rag_chunks_included: int = Field(serialization_alias="ragChunksIncluded")
    rag_chunks_filtered: int = Field(serialization_alias="ragChunksFiltered")
    state_packet_present: bool = Field(default=False, serialization_alias="statePacketPresent")
    state_packet_tokens: int = Field(default=0, serialization_alias="statePacketTokens")
    state_packet: dict | None = Field(default=None, serialization_alias="statePacket")
    total_tokens_estimate: int = Field(serialization_alias="totalTokensEstimate")
    sections: list[ContextSection]


@dataclass(slots=True)
class ContextAssemblyResult:
    """Combined assembled context plus inspection metadata."""

    assembled: AssembledContext
    inspection: ContextInspection


class ContextEngine(Protocol):
    """Interface for context assembly engines."""

    async def assemble(
        self,
        *,
        conversation_messages: list[dict[str, str]],
        conversation_summary: str,
        rag_chunks: list[dict] | None,
        user_message: str,
        client: AsyncAnthropic | None,
        state_packet: SessionStatePacket | dict | None = None,
        model: str | None = None,
    ) -> ContextAssemblyResult:
        """Assemble context and emit inspection metadata."""


class HierarchicalContextEngine:
    """Default summarize-first context engine with light pruning/inspection."""

    _candidate_patterns: tuple[tuple[str, re.Pattern[str]], ...] = (
        (
            "preference",
            re.compile(
                r"\b(i prefer|i like|i love|i hate|always|never)\b",
                re.IGNORECASE,
            ),
        ),
        (
            "decision",
            re.compile(r"\b(decided|decision|we chose|i chose)\b", re.IGNORECASE),
        ),
        (
            "commitment",
            re.compile(r"\b(i will|i need to|remind me|i should)\b", re.IGNORECASE),
        ),
        (
            "project_state",
            re.compile(
                r"\b(project|milestone|deadline|launch|ship)\b",
                re.IGNORECASE,
            ),
        ),
        (
            "relationship",
            re.compile(
                r"\b(meet|met with|emailed|called|my manager|my friend)\b",
                re.IGNORECASE,
            ),
        ),
        (
            "knowledge",
            re.compile(
                r"\b(remember that|important|key point|note that)\b",
                re.IGNORECASE,
            ),
        ),
    )

    async def assemble(
        self,
        *,
        conversation_messages: list[dict[str, str]],
        conversation_summary: str,
        rag_chunks: list[dict] | None,
        user_message: str,
        client: AsyncAnthropic | None,
        state_packet: SessionStatePacket | dict | None = None,
        model: str | None = None,
    ) -> ContextAssemblyResult:
        pruned_messages, pruned_count, pruned_characters = self._prune_messages(
            conversation_messages,
        )
        durable_memory_candidates = self._extract_durable_memory_candidates(pruned_messages)
        assembled_state_packet = _coerce_state_packet(state_packet)

        assembled = await assemble_context(
            conversation_messages=pruned_messages,
            conversation_summary=conversation_summary,
            state_packet=state_packet,
            rag_chunks=rag_chunks,
            user_message=user_message,
            client=client,
            model=model,
        )

        derived_state_packet_render = ""
        if assembled_state_packet is not None:
            derived_state_packet_render = render_session_state_packet(
                assembled_state_packet,
                token_budget=max(assembled.state_packet_tokens, 256),
            )
        state_packet_present = assembled.state_packet_used or bool(derived_state_packet_render)
        state_packet_tokens = assembled.state_packet_tokens or estimate_tokens(
            derived_state_packet_render
        )

        sections = [
            ContextSection(
                name="state_packet",
                tokens=state_packet_tokens,
                item_count=(
                    sum(
                        len(items)
                        for items in [
                            assembled_state_packet.open_loops,
                            assembled_state_packet.facts,
                            assembled_state_packet.preferences,
                            assembled_state_packet.active_entities,
                            assembled_state_packet.recent_artifacts,
                            assembled_state_packet.commitments,
                            assembled_state_packet.decisions,
                        ]
                    )
                    if assembled_state_packet is not None
                    else 0
                ),
                present=state_packet_present,
            ),
            ContextSection(
                name="conversation",
                tokens=estimate_tokens(assembled.conversation_context),
                item_count=len(pruned_messages),
                present=bool(assembled.conversation_context),
            ),
            ContextSection(
                name="session_summary",
                tokens=estimate_tokens(conversation_summary),
                item_count=1 if conversation_summary else 0,
                present=bool(conversation_summary),
            ),
            ContextSection(
                name="retrieval",
                tokens=estimate_tokens(assembled.rag_context),
                item_count=assembled.rag_chunks_included,
                present=bool(assembled.rag_context),
            ),
            ContextSection(
                name="user_message",
                tokens=estimate_tokens(user_message),
                item_count=1,
                present=bool(user_message),
            ),
        ]

        inspection = ContextInspection(
            history_summarized=assembled.history_summarized,
            pruned_messages=pruned_count,
            pruned_characters=pruned_characters,
            durable_memory_candidates=durable_memory_candidates,
            rag_chunks_included=assembled.rag_chunks_included,
            rag_chunks_filtered=assembled.rag_chunks_filtered,
            state_packet_present=state_packet_present,
            state_packet_tokens=state_packet_tokens,
            state_packet=(
                packet_to_debug_dict(assembled_state_packet)
                if assembled_state_packet is not None
                else None
            ),
            total_tokens_estimate=assembled.total_tokens_estimate,
            sections=sections,
        )

        return ContextAssemblyResult(assembled=assembled, inspection=inspection)

    def _prune_messages(
        self,
        messages: list[dict[str, str]],
    ) -> tuple[list[dict[str, str]], int, int]:
        """Trim oversized historical tool outputs before context assembly."""
        if not messages:
            return [], 0, 0

        assistant_indexes = [
            idx for idx, msg in enumerate(messages) if msg.get("role") == "assistant"
        ]
        protected_indexes = set(assistant_indexes[-3:])

        pruned_messages: list[dict[str, str]] = []
        pruned_count = 0
        pruned_characters = 0

        for idx, msg in enumerate(messages):
            content = msg.get("content", "")
            should_prune = (
                idx not in protected_indexes
                and msg.get("role") == "assistant"
                and msg.get("agent") == "tools"
                and len(content) > 4_000
            )

            if not should_prune:
                pruned_messages.append(msg)
                continue

            trimmed = (
                f"{content[:1_500]}\n...\n{content[-1_000:]}\n"
                f"[Older tool result trimmed from {len(content)} characters for prompt efficiency.]"
            )
            pruned_messages.append({**msg, "content": trimmed})
            pruned_count += 1
            pruned_characters += max(len(content) - len(trimmed), 0)

        return pruned_messages, pruned_count, pruned_characters

    def _extract_durable_memory_candidates(
        self,
        messages: list[dict[str, str]],
    ) -> list[DurableMemoryCandidate]:
        """Heuristically identify candidate durable facts before compaction."""
        candidates: list[DurableMemoryCandidate] = []
        seen: set[tuple[str, str]] = set()

        for msg in messages:
            content = (msg.get("content") or "").strip()
            if not content:
                continue

            for category, pattern in self._candidate_patterns:
                if not pattern.search(content):
                    continue

                excerpt = content[:220] + ("..." if len(content) > 220 else "")
                key = (category, excerpt)
                if key in seen:
                    break

                seen.add(key)
                candidates.append(
                    DurableMemoryCandidate(
                        category=category,
                        excerpt=excerpt,
                        source_role=msg.get("role", "unknown"),
                    ),
                )
                break

            if len(candidates) >= 6:
                break

        return candidates


_DEFAULT_ENGINE = HierarchicalContextEngine()


def get_default_context_engine() -> ContextEngine:
    """Return the default context engine implementation."""
    return _DEFAULT_ENGINE


def _coerce_state_packet(packet: SessionStatePacket | dict | None) -> SessionStatePacket | None:
    if packet is None:
        return None
    if isinstance(packet, SessionStatePacket):
        return packet
    return SessionStatePacket.model_validate(packet)

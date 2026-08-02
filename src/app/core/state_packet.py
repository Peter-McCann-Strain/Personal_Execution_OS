"""Structured session state packet extraction, rendering, and regression helpers."""

from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime
from numbers import Real
from typing import Any

from src.app.core.context_budget import estimate_tokens
from src.app.domain.models import (
    ChatResponse,
    SessionStatePacket,
    StatePacketArtifact,
    StatePacketItem,
    StatePacketSource,
)

_PREFERENCE_RE = re.compile(r"\b(i prefer|i like|i love|i hate|always|never)\b", re.IGNORECASE)
_COMMITMENT_RE = re.compile(
    r"\b(i will|i need to|remind me|follow up|send|call|book|schedule)\b",
    re.IGNORECASE,
)
_DECISION_RE = re.compile(r"\b(decided|decision|we chose|i chose|plan is)\b", re.IGNORECASE)
_FACT_RE = re.compile(
    r"\b(remember that|important|note that|my name is|i work at|i live in)\b",
    re.IGNORECASE,
)
_OPEN_LOOP_RE = re.compile(
    r"\?$|\b(can you|could you|please|what about|follow up on)\b",
    re.IGNORECASE,
)
_ENTITY_TOKEN_RE = r"[A-Z][A-Za-z0-9]*(?:[._-][A-Za-z0-9]+)*"
_ENTITY_RE = re.compile(rf"\b({_ENTITY_TOKEN_RE}(?:\s+{_ENTITY_TOKEN_RE}){{0,2}})\b")
_MAX_ITEM_CHARS = 220
_MAX_SUMMARY_CHARS = 700
_TOKEN_BUDGET_HEADROOM = 8
_DATE_WORDS = frozenset(
    {
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
        "today",
        "yesterday",
        "tomorrow",
    }
)
_NON_ENTITY_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "assistant",
        "because",
        "can",
        "could",
        "good",
        "great",
        "hello",
        "here",
        "hi",
        "how",
        "i",
        "it",
        "message",
        "need",
        "needs",
        "nothing",
        "please",
        "quiet",
        "saved",
        "should",
        "thanks",
        "that",
        "the",
        "there",
        "they",
        "this",
        "those",
        "user",
        "we",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "you",
        "your",
    }
)
_NON_ENTITY_STARTERS = frozenset(
    {
        "book",
        "call",
        "email",
        "follow",
        "reply",
        "research",
        "schedule",
        "send",
        "tool",
        "use",
    }
)


@dataclass(frozen=True, slots=True)
class EquivalenceCase:
    """Deterministic benchmark case for state-packet coverage checks."""

    case_id: str
    packet: SessionStatePacket
    expected_fragments: tuple[str, ...]


def build_session_state_packet(
    conversation_messages: list[dict[str, str]],
    *,
    conversation_summary: str = "",
    previous_packet: SessionStatePacket | None = None,
    response: ChatResponse | None = None,
) -> SessionStatePacket:
    """Build a machine-readable compacted session state packet.

    The packet is deterministic and source-backed. Recent message-derived items win over
    older packet items, while existing packet items are retained when they remain useful.
    """
    open_loops = _extract_items(conversation_messages, matcher=_OPEN_LOOP_RE)
    facts = _extract_items(conversation_messages, matcher=_FACT_RE)
    preferences = _extract_items(conversation_messages, matcher=_PREFERENCE_RE)
    commitments = _extract_items(conversation_messages, matcher=_COMMITMENT_RE)
    decisions = _extract_items(conversation_messages, matcher=_DECISION_RE)
    active_entities = _extract_entities(conversation_messages)
    recent_artifacts = _extract_artifacts(conversation_messages, response=response)

    if previous_packet is not None:
        open_loops = _merge_items(open_loops, previous_packet.open_loops)
        facts = _merge_items(facts, previous_packet.facts)
        preferences = _merge_items(preferences, previous_packet.preferences)
        commitments = _merge_items(commitments, previous_packet.commitments)
        decisions = _merge_items(decisions, previous_packet.decisions)
        active_entities = _merge_items(active_entities, previous_packet.active_entities)
        recent_artifacts = _merge_artifacts(recent_artifacts, previous_packet.recent_artifacts)

    return SessionStatePacket(
        open_loops=open_loops,
        facts=facts,
        preferences=preferences,
        active_entities=active_entities,
        recent_artifacts=recent_artifacts,
        commitments=commitments,
        decisions=decisions,
        conversation_summary=(
            _truncate_text(conversation_summary, _MAX_SUMMARY_CHARS)
            or (previous_packet.conversation_summary if previous_packet is not None else "")
        ),
        updated_at=datetime.now(UTC),
    )


def merge_persisted_artifacts(
    packet: SessionStatePacket | None,
    persisted_artifacts: list[object] | None,
) -> SessionStatePacket | None:
    """Merge stored artifacts into a state packet without disturbing other sections."""
    if not persisted_artifacts:
        return packet

    converted = _coerce_persisted_artifacts(persisted_artifacts)
    derived_sections = _coerce_persisted_state_sections(persisted_artifacts)
    if not converted:
        return packet

    if packet is None:
        return SessionStatePacket(
            recent_artifacts=converted,
            open_loops=derived_sections["open_loops"],
            facts=derived_sections["facts"],
            preferences=derived_sections["preferences"],
            active_entities=derived_sections["active_entities"],
            commitments=derived_sections["commitments"],
            decisions=derived_sections["decisions"],
        )

    return packet.model_copy(
        update={
            "open_loops": _merge_items(packet.open_loops, derived_sections["open_loops"]),
            "facts": _merge_items(packet.facts, derived_sections["facts"]),
            "preferences": _merge_items(packet.preferences, derived_sections["preferences"]),
            "active_entities": _merge_items(
                packet.active_entities,
                derived_sections["active_entities"],
            ),
            "commitments": _merge_items(packet.commitments, derived_sections["commitments"]),
            "decisions": _merge_items(packet.decisions, derived_sections["decisions"]),
            "recent_artifacts": _merge_artifacts(packet.recent_artifacts, converted),
        }
    )


def render_session_state_packet(
    packet: SessionStatePacket | dict | None,
    *,
    token_budget: int | None = None,
) -> str:
    """Render a deterministic prompt-safe state packet within an optional budget."""
    if packet is None:
        return ""

    if isinstance(packet, dict):
        packet = SessionStatePacket.model_validate(packet)

    budget = token_budget if token_budget is not None else 2_048
    if budget <= 0:
        return ""
    effective_budget = budget + _TOKEN_BUDGET_HEADROOM

    sections: list[tuple[str, list[str]]] = [
        ("open_loops", [_format_state_item(item) for item in packet.open_loops]),
        ("commitments", [_format_state_item(item) for item in packet.commitments]),
        ("decisions", [_format_state_item(item) for item in packet.decisions]),
        ("preferences", [_format_state_item(item) for item in packet.preferences]),
        ("active_entities", [_format_state_item(item) for item in packet.active_entities]),
        ("facts", [_format_state_item(item) for item in packet.facts]),
        (
            "recent_artifacts",
            [_format_artifact(item) for item in packet.recent_artifacts],
        ),
    ]
    if packet.conversation_summary:
        sections.append(
            ("conversation_summary", [packet.conversation_summary]),
        )

    lines = ["<session_state_packet>"]

    for section_name, items in sections:
        if not items:
            continue

        header = f"{section_name}:"
        section_lines = [header]
        for item in items:
            candidate_line = f"- {item}"
            candidate_block = "\n".join([*section_lines, candidate_line])
            candidate_text = "\n".join([*lines, candidate_block, "</session_state_packet>"])
            if estimate_tokens(candidate_text) > effective_budget:
                break
            section_lines.append(candidate_line)

        if len(section_lines) == 1:
            continue

        block = "\n".join(section_lines)
        lines.append(block)

    lines.append("</session_state_packet>")
    rendered = "\n".join(lines)
    if estimate_tokens(rendered) > effective_budget and len(lines) <= 2:
        return ""
    return rendered


def evaluate_state_packet_equivalence(case: EquivalenceCase) -> float:
    """Return the coverage ratio of expected fragments preserved by the state packet."""
    haystack = "\n".join(
        [
            render_session_state_packet(case.packet, token_budget=4_096),
            case.packet.conversation_summary,
        ]
    ).lower()
    if not case.expected_fragments:
        return 1.0

    matched = sum(1 for fragment in case.expected_fragments if fragment.lower() in haystack)
    return matched / len(case.expected_fragments)


def packet_to_debug_dict(packet: SessionStatePacket) -> dict:
    """Expose stable JSON-friendly state-packet data for inspection APIs/tests."""
    return packet.model_dump(mode="json")


def _extract_items(
    conversation_messages: list[dict[str, str]],
    *,
    matcher: re.Pattern[str],
) -> list[StatePacketItem]:
    items: OrderedDict[str, StatePacketItem] = OrderedDict()

    for index, message in enumerate(reversed(conversation_messages)):
        content = _normalize_content(message.get("content", ""))
        if not content or not matcher.search(content):
            continue

        source = _source_from_message(message, index=index)
        key = _normalize_key(content)
        if key in items:
            continue
        items[key] = StatePacketItem(
            value=_truncate_text(content, _MAX_ITEM_CHARS),
            sources=[source],
        )
        if len(items) >= 6:
            break

    return list(items.values())


def _extract_entities(conversation_messages: list[dict[str, str]]) -> list[StatePacketItem]:
    items: OrderedDict[str, StatePacketItem] = OrderedDict()

    for index, message in enumerate(reversed(conversation_messages)):
        content = message.get("content", "")
        if not content:
            continue
        for match in _ENTITY_RE.finditer(content):
            entity = match.group(1).strip()
            if not _looks_like_entity(entity):
                continue
            key = _normalize_key(entity)
            if key in items:
                continue
            items[key] = StatePacketItem(
                value=entity,
                sources=[_source_from_message(message, index=index)],
            )
            if len(items) >= 6:
                return list(items.values())

    return list(items.values())


def _looks_like_entity(entity: str) -> bool:
    words = [word.strip(".,:;!?()[]{}") for word in entity.split() if word.strip(".,:;!?()[]{}")]
    if not words:
        return False

    lowered = [word.lower() for word in words]
    if entity.lower() in {"assistant", "user", "current message"}:
        return False
    if all(word in _DATE_WORDS or word.isdigit() for word in lowered):
        return False
    if len(lowered) > 1 and lowered[0] in _NON_ENTITY_STARTERS:
        return False
    if len(lowered) == 1 and lowered[0] in _NON_ENTITY_WORDS:
        return False
    return not all(word in _NON_ENTITY_WORDS for word in lowered)


def _extract_artifacts(
    conversation_messages: list[dict[str, str]],
    *,
    response: ChatResponse | None,
) -> list[StatePacketArtifact]:
    artifacts: OrderedDict[str, StatePacketArtifact] = OrderedDict()

    for index, message in enumerate(reversed(conversation_messages)):
        role = message.get("role")
        agent = message.get("agent")
        content = _normalize_content(message.get("content", ""))
        if role != "assistant" or not content:
            continue
        if agent == "tools" or "tool" in content.lower():
            summary = _truncate_text(content, _MAX_ITEM_CHARS)
            key = _normalize_key(summary)
            if key in artifacts:
                continue
            artifacts[key] = StatePacketArtifact(
                artifact_type=agent or "assistant_output",
                summary=summary,
                sources=[_source_from_message(message, index=index)],
            )
        if len(artifacts) >= 4:
            break

    if response is not None:
        for tool_call in response.metadata.get("tool_calls", []):
            if not isinstance(tool_call, dict):
                continue
            name = str(tool_call.get("name", "tool"))
            summary = f"{name}: {tool_call.get('status', 'planned')}"
            key = _normalize_key(summary)
            if key in artifacts:
                continue
            artifacts[key] = StatePacketArtifact(
                artifact_type="tool_call",
                summary=summary,
                sources=[
                    StatePacketSource(
                        source_id=response.metadata.get("trace_id", "response"),
                        source_type="response_tool_call",
                        excerpt=_truncate_text(summary, _MAX_ITEM_CHARS),
                    )
                ],
            )
            if len(artifacts) >= 4:
                break

    return list(artifacts.values())


def _merge_items(
    primary: list[StatePacketItem],
    secondary: list[StatePacketItem],
) -> list[StatePacketItem]:
    merged: OrderedDict[str, StatePacketItem] = OrderedDict()

    for item in [*primary, *secondary]:
        key = _normalize_key(item.value)
        if key in merged:
            continue
        merged[key] = item
        if len(merged) >= 6:
            break

    return list(merged.values())


def _merge_artifacts(
    primary: list[StatePacketArtifact],
    secondary: list[StatePacketArtifact],
) -> list[StatePacketArtifact]:
    merged: OrderedDict[str, StatePacketArtifact] = OrderedDict()

    for artifact in [*primary, *secondary]:
        key = _normalize_key(artifact.summary)
        if key in merged:
            continue
        merged[key] = artifact
        if len(merged) >= 4:
            break

    return list(merged.values())


def _coerce_persisted_artifacts(persisted_artifacts: list[object]) -> list[StatePacketArtifact]:
    artifacts: OrderedDict[str, StatePacketArtifact] = OrderedDict()

    for index, record in enumerate(persisted_artifacts):
        artifact = _coerce_persisted_artifact(record, index=index)
        if artifact is None:
            continue
        key = _normalize_key(artifact.summary)
        if key in artifacts:
            continue
        artifacts[key] = artifact
        if len(artifacts) >= 4:
            break

    return list(artifacts.values())


def _coerce_persisted_state_sections(
    persisted_artifacts: list[object],
) -> dict[str, list[StatePacketItem]]:
    sections = {
        "open_loops": [],
        "facts": [],
        "preferences": [],
        "active_entities": [],
        "commitments": [],
        "decisions": [],
    }

    for index, record in enumerate(persisted_artifacts):
        derived = _derive_state_items_from_artifact(record, index=index)
        for section_name, items in derived.items():
            sections[section_name] = _merge_items(sections[section_name], items)

    return sections


def _derive_state_items_from_artifact(
    record: object,
    *,
    index: int,
) -> dict[str, list[StatePacketItem]]:
    source = _source_from_persisted_artifact(record, index=index)
    artifact_type = str(_maybe_attr(record, "artifact_type") or "")
    summary = _normalize_content(_maybe_attr(record, "summary") or "")
    payload = _normalized_artifact_payload(_maybe_attr(record, "payload"))

    sections = {
        "open_loops": [],
        "facts": [],
        "preferences": [],
        "active_entities": [],
        "commitments": [],
        "decisions": [],
    }
    entity_texts: list[str] = [summary] if summary else []

    if artifact_type == "response_envelope":
        content_texts = _response_envelope_texts(payload)
        if content_texts:
            _merge_structured_text_sections(sections, content_texts, source)
            entity_texts.extend(content_texts)
        _merge_citation_entities(sections, payload, entity_texts, source)
        _merge_tool_execution_sections(
            sections,
            payload.get("tool_events") or payload.get("tool_calls"),
            source,
            tool_names=payload.get("tool_names"),
            tool_statuses=payload.get("tool_statuses"),
        )
    elif artifact_type == "tool_summary":
        _merge_tool_execution_sections(
            sections,
            payload.get("tool_events") or payload.get("tool_calls"),
            source,
            tool_names=payload.get("tool_names"),
            tool_statuses=payload.get("tool_statuses"),
        )
    elif artifact_type == "research_report":
        key_takeaway = _normalize_content(str(payload.get("key_takeaway") or ""))
        recommendation = _normalize_content(str(payload.get("recommendation") or ""))
        if key_takeaway:
            sections["facts"].append(_state_item_from_artifact(key_takeaway, source))
            entity_texts.append(key_takeaway)
        if recommendation:
            sections["decisions"].append(_state_item_from_artifact(recommendation, source))
            entity_texts.append(recommendation)

        citations = payload.get("citations")
        if isinstance(citations, list):
            for citation in citations[:6]:
                if not isinstance(citation, dict):
                    continue
                label = _normalize_content(str(citation.get("label") or ""))
                excerpt = _normalize_content(str(citation.get("excerpt") or ""))
                if label:
                    sections["active_entities"] = _merge_items(
                        sections["active_entities"],
                        _state_items_from_named_values([label], source),
                    )
                    entity_texts.append(label)
                if excerpt:
                    entity_texts.append(excerpt)

    elif artifact_type == "email_triage":
        sender = _normalize_content(str(payload.get("sender") or ""))
        subject_summary = _normalize_content(str(payload.get("subject_summary") or ""))
        suggested_action = _normalize_content(str(payload.get("suggested_action") or ""))
        response_deadline = _normalize_content(str(payload.get("response_deadline") or ""))

        if sender or subject_summary:
            fact = "Email"
            if sender:
                fact += f" from {sender}"
            if subject_summary:
                fact += f" about {subject_summary}"
            sections["facts"].append(_state_item_from_artifact(fact + ".", source))
        if sender:
            sections["active_entities"] = _merge_items(
                sections["active_entities"],
                _state_items_from_named_values([sender], source),
            )

        if suggested_action:
            sections["open_loops"].append(_state_item_from_artifact(suggested_action, source))
        if suggested_action and response_deadline:
            sections["commitments"].append(
                _state_item_from_artifact(f"{suggested_action} by {response_deadline}.", source)
            )

        for text in (sender, subject_summary, suggested_action):
            if text:
                entity_texts.append(text)

    sections["active_entities"] = _merge_items(
        sections["active_entities"],
        _extract_entities_from_texts(entity_texts, source),
    )
    return sections


def _normalized_artifact_payload(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    preserved = payload.get("preserved")
    if payload.get("_compacted_by") and isinstance(preserved, dict):
        return {str(key): value for key, value in preserved.items()}
    return {str(key): value for key, value in payload.items()}


def _response_envelope_texts(payload: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    content_blocks = payload.get("content_blocks")
    if isinstance(content_blocks, list):
        for block in content_blocks:
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type", "text")).strip().lower()
            title = _normalize_content(str(block.get("title") or ""))
            text = _normalize_content(str(block.get("text") or ""))
            items = (
                [
                    _normalize_content(str(item))
                    for item in block.get("items", [])
                    if _normalize_content(str(item))
                ]
                if isinstance(block.get("items"), list)
                else []
            )

            if block_type in {"field", "label_value"} and title and text:
                texts.append(f"{title}: {text}")
            elif text:
                texts.append(text)
            elif title:
                texts.append(title)

            texts.extend(items)

    content_preview = _normalize_content(str(payload.get("content_preview") or ""))
    if content_preview:
        texts.extend(_split_structured_fragments(content_preview))

    deduped: OrderedDict[str, str] = OrderedDict()
    for text in texts:
        if not text:
            continue
        deduped.setdefault(_normalize_key(text), text)
        if len(deduped) >= 12:
            break
    return list(deduped.values())


def _split_structured_fragments(text: str) -> list[str]:
    fragments = [
        _normalize_content(fragment) for fragment in re.split(r"(?:\n+|(?<=[.?!])\s+|;\s+)", text)
    ]
    return [fragment for fragment in fragments if fragment]


def _merge_structured_text_sections(
    sections: dict[str, list[StatePacketItem]],
    texts: list[str],
    source: StatePacketSource,
) -> None:
    prefix_map = {
        "recommendation:": "decisions",
        "decision:": "decisions",
        "next step:": "open_loops",
        "deadline:": "commitments",
        "category:": "facts",
    }
    for text in texts:
        lowered = text.lower()
        for prefix, section_name in prefix_map.items():
            if not lowered.startswith(prefix):
                continue
            value = text.split(":", 1)[1].strip() or text
            if section_name == "commitments" and not value.lower().startswith("deadline"):
                value = f"Deadline: {value}"
            sections[section_name] = _merge_items(
                sections[section_name],
                [_state_item_from_artifact(value, source)],
            )
            break


def _merge_citation_entities(
    sections: dict[str, list[StatePacketItem]],
    payload: dict[str, Any],
    entity_texts: list[str],
    source: StatePacketSource,
) -> None:
    citations = payload.get("citations")
    if isinstance(citations, list):
        for citation in citations[:6]:
            if not isinstance(citation, dict):
                continue
            label = _normalize_content(str(citation.get("label") or ""))
            excerpt = _normalize_content(str(citation.get("excerpt") or ""))
            if label:
                sections["active_entities"] = _merge_items(
                    sections["active_entities"],
                    _state_items_from_named_values([label], source),
                )
                entity_texts.append(label)
            if excerpt:
                entity_texts.append(excerpt)

    citation_labels = payload.get("citation_labels")
    if isinstance(citation_labels, list):
        normalized_labels = [
            _normalize_content(str(label))
            for label in citation_labels[:8]
            if _normalize_content(str(label))
        ]
        if normalized_labels:
            sections["active_entities"] = _merge_items(
                sections["active_entities"],
                _state_items_from_named_values(normalized_labels, source),
            )
            entity_texts.extend(normalized_labels)


def _merge_tool_execution_sections(
    sections: dict[str, list[StatePacketItem]],
    tool_data: object,
    source: StatePacketSource,
    *,
    tool_names: object | None = None,
    tool_statuses: object | None = None,
) -> None:
    events: list[tuple[str, str]] = []

    if isinstance(tool_data, list):
        for raw_event in tool_data[:8]:
            if not isinstance(raw_event, dict):
                continue
            name = _normalize_content(str(raw_event.get("name") or ""))
            status = _normalize_content(str(raw_event.get("status") or "planned")).lower()
            if name:
                events.append((name, status or "planned"))

    names = tool_names if isinstance(tool_names, list) else []
    statuses = tool_statuses if isinstance(tool_statuses, list) else []
    for index, raw_name in enumerate(names[:8]):
        name = _normalize_content(str(raw_name))
        if not name:
            continue
        status = "planned"
        if index < len(statuses):
            status = _normalize_content(str(statuses[index])).lower() or "planned"
        events.append((name, status))

    deduped: OrderedDict[str, tuple[str, str]] = OrderedDict()
    for name, status in events:
        deduped.setdefault(f"{_normalize_key(name)}::{status}", (name, status))
        if len(deduped) >= 6:
            break

    for name, status in deduped.values():
        if status in {"planned", "pending"}:
            sections["open_loops"] = _merge_items(
                sections["open_loops"],
                [_state_item_from_artifact(f"Pending tool action: {name}.", source)],
            )
        elif status in {"failed", "error"}:
            sections["open_loops"] = _merge_items(
                sections["open_loops"],
                [_state_item_from_artifact(f"Follow up on failed tool: {name}.", source)],
            )
        elif status in {"executed", "confirmed"}:
            sections["facts"] = _merge_items(
                sections["facts"],
                [_state_item_from_artifact(f"Executed tool: {name}.", source)],
            )
        elif status == "cancelled":
            sections["facts"] = _merge_items(
                sections["facts"],
                [_state_item_from_artifact(f"Cancelled tool action: {name}.", source)],
            )


def _coerce_persisted_artifact(
    record: object,
    *,
    index: int,
) -> StatePacketArtifact | None:
    artifact_type = _maybe_attr(record, "artifact_type")
    summary = _normalize_content(_maybe_attr(record, "summary") or "")
    if not artifact_type or not summary:
        return None

    source_id = (
        _maybe_attr(record, "source_id") or _maybe_attr(record, "trace_id") or f"artifact-{index}"
    )
    created_at = _maybe_attr(record, "created_at")
    timestamp = created_at.isoformat() if hasattr(created_at, "isoformat") else None

    return StatePacketArtifact(
        artifact_type=str(artifact_type),
        summary=_truncate_text(summary, _MAX_ITEM_CHARS),
        scope=str(_maybe_attr(record, "scope") or "session"),
        sources=[
            _source_from_persisted_artifact(
                record,
                index=index,
                source_id=str(source_id),
                source_type=f"artifact_{artifact_type}",
                timestamp=timestamp,
                excerpt=_truncate_text(summary, 120),
            )
        ],
    )


def _source_from_persisted_artifact(
    record: object,
    *,
    index: int,
    source_id: str | None = None,
    source_type: str | None = None,
    timestamp: str | None = None,
    excerpt: str | None = None,
) -> StatePacketSource:
    resolved_source_id = source_id or (
        _maybe_attr(record, "source_id") or _maybe_attr(record, "trace_id") or f"artifact-{index}"
    )
    created_at = _maybe_attr(record, "created_at")
    resolved_timestamp = timestamp or (
        created_at.isoformat() if hasattr(created_at, "isoformat") else None
    )
    resolved_type = source_type or f"artifact_{_maybe_attr(record, 'artifact_type') or 'unknown'}"
    resolved_excerpt = excerpt or _truncate_text(str(_maybe_attr(record, "summary") or ""), 120)
    return StatePacketSource(
        source_id=str(resolved_source_id),
        source_type=str(resolved_type),
        timestamp=resolved_timestamp,
        excerpt=resolved_excerpt,
    )


def _source_from_message(message: dict[str, str], *, index: int) -> StatePacketSource:
    timestamp = message.get("timestamp")
    source_id = timestamp or f"message-{index}"
    return StatePacketSource(
        source_id=str(source_id),
        source_type=f"conversation_{message.get('role', 'unknown')}",
        timestamp=timestamp,
        excerpt=_truncate_text(message.get("content", ""), 120),
    )


def _state_item_from_artifact(value: str, source: StatePacketSource) -> StatePacketItem:
    return StatePacketItem(
        value=_truncate_text(value, _MAX_ITEM_CHARS),
        sources=[source],
    )


def _extract_entities_from_texts(
    texts: list[str],
    source: StatePacketSource,
) -> list[StatePacketItem]:
    items: OrderedDict[str, StatePacketItem] = OrderedDict()

    for text in texts:
        if not text:
            continue
        for match in _ENTITY_RE.finditer(text):
            entity = match.group(1).strip()
            if not _looks_like_entity(entity):
                continue
            key = _normalize_key(entity)
            if key in items:
                continue
            items[key] = StatePacketItem(value=entity, sources=[source])
            if len(items) >= 6:
                return list(items.values())

    return list(items.values())


def _state_items_from_named_values(
    values: list[str],
    source: StatePacketSource,
) -> list[StatePacketItem]:
    items: OrderedDict[str, StatePacketItem] = OrderedDict()

    for value in values:
        normalized = _normalize_content(value)
        if not normalized or not _looks_like_entity(normalized):
            continue
        key = _normalize_key(normalized)
        if key in items:
            continue
        items[key] = StatePacketItem(value=normalized, sources=[source])
        if len(items) >= 6:
            break

    return list(items.values())


def _format_state_item(item: StatePacketItem) -> str:
    return item.value


def _format_artifact(artifact: StatePacketArtifact) -> str:
    return (
        artifact.summary
        if artifact.artifact_type == "tool_call"
        else f"{artifact.artifact_type}: {artifact.summary}"
    )


def _normalize_content(content: str) -> str:
    compact = " ".join(content.split())
    return compact.strip()


def _normalize_key(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _truncate_text(text: str, max_chars: int) -> str:
    normalized = _normalize_content(text)
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 3].rstrip() + "..."


def _coerce_numeric(value: object) -> float | None:
    if isinstance(value, Real) and not isinstance(value, bool):
        return float(value)
    return None


def _maybe_attr(record: object, name: str) -> Any | None:
    if isinstance(record, dict):
        return record.get(name)
    return getattr(record, name, None)

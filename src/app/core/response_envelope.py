"""Canonical response envelope construction and channel-aware rendering."""

from __future__ import annotations

import uuid
from typing import Any

import structlog

from src.app.core.response_style import format_telegram_text, normalize_response_text
from src.app.domain.models import (
    ChannelHints,
    ChatResponse,
    Intent,
    MessageInput,
    ResponseCitation,
    ResponseContentBlock,
    ResponseEnvelope,
    ResponseQuality,
    ResponseToolEvent,
)

logger = structlog.get_logger()
_TELEGRAM_SOFT_LIMIT = 3_500


def build_response_envelope(
    response: ChatResponse,
    *,
    message: MessageInput,
    intent: Intent,
    quality: ResponseQuality | None,
) -> ResponseEnvelope:
    """Construct the canonical internal response envelope."""
    metadata = response.metadata
    tool_events = _build_tool_events(metadata)

    channel_hints = ChannelHints(
        preferred_format="plain_text",
        prefer_chunking=message.source == "telegram",
        prefer_reply_anchor=message.source == "telegram",
        spoken_style=message.source == "voice",
    )

    return ResponseEnvelope(
        response_id=str(metadata.get("response_id") or uuid.uuid4()),
        interaction_id=_coerce_optional_str(metadata.get("interaction_id")),
        trace_id=_coerce_optional_str(metadata.get("trace_id")),
        workflow_id=_coerce_optional_str(metadata.get("workflow_id")),
        workflow_status=_coerce_optional_str(metadata.get("workflow_status")),
        specialist=str(intent.specialist),
        content_blocks=_build_content_blocks(response),
        citations=_build_citations(metadata),
        actions=[],
        tool_events=tool_events,
        quality=quality,
        safety_flags=[str(flag) for flag in metadata.get("safety_flags", [])],
        channel_hints=channel_hints,
    )


def render_response_envelope(
    envelope: ResponseEnvelope,
    *,
    message: MessageInput,
    metadata: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Render the envelope for the target channel and return text plus metrics."""
    raw_text = _render_content_blocks(envelope.content_blocks).strip()
    rendered = normalize_response_text(
        raw_text,
        source=message.source,
        specialist=envelope.specialist,
        message_content=message.content,
        metadata=metadata,
    )

    channel_metrics: dict[str, Any] = {
        "renderer": message.source,
        "render_passed": True,
        "chunk_count": 1,
        "content_block_count": len(envelope.content_blocks),
        "citation_count": len(envelope.citations),
        "tool_event_count": len(envelope.tool_events),
    }

    if message.source == "telegram":
        rendered = format_telegram_text(rendered)
        chunk_count = len(split_telegram_text(rendered))
        channel_metrics.update(
            {
                "preferred_format": "plain_text",
                "chunk_count": chunk_count,
                "reply_anchor_requested": envelope.channel_hints.prefer_reply_anchor,
                "soft_limit": _TELEGRAM_SOFT_LIMIT,
            },
        )
    elif message.source == "voice":
        channel_metrics.update(
            {
                "preferred_format": "spoken_text",
                "spoken_style": True,
            },
        )
    else:
        channel_metrics["preferred_format"] = "rich_text"

    return rendered, channel_metrics


def split_telegram_text(text: str, *, soft_limit: int = _TELEGRAM_SOFT_LIMIT) -> list[str]:
    """Split a Telegram message into readable chunks below the soft limit."""
    stripped = text.strip()
    if not stripped:
        return [""]
    if len(stripped) <= soft_limit:
        return [stripped]

    chunks: list[str] = []
    current = stripped
    while len(current) > soft_limit:
        split_at = current.rfind("\n\n", 0, soft_limit)
        if split_at < 0:
            split_at = current.rfind("\n", 0, soft_limit)
        if split_at < 0:
            split_at = current.rfind(" ", 0, soft_limit)
        if split_at < 0:
            split_at = soft_limit

        chunk = current[:split_at].strip()
        if not chunk:
            chunk = current[:soft_limit].strip()
            split_at = soft_limit

        chunks.append(chunk)
        current = current[split_at:].strip()

    if current:
        chunks.append(current)
    return chunks


def _coerce_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _build_content_blocks(response: ChatResponse) -> list[ResponseContentBlock]:
    metadata = response.metadata
    raw_blocks = metadata.get("content_blocks")
    if isinstance(raw_blocks, list):
        parsed_blocks = _parse_content_blocks(raw_blocks)
        if parsed_blocks:
            return parsed_blocks

    fallback = response.content.strip()
    if not fallback:
        return []
    return [ResponseContentBlock(type="text", text=fallback)]


def _parse_content_blocks(raw_blocks: list[Any]) -> list[ResponseContentBlock]:
    parsed: list[ResponseContentBlock] = []
    for index, raw_block in enumerate(raw_blocks):
        if isinstance(raw_block, ResponseContentBlock):
            block = raw_block
        elif isinstance(raw_block, dict):
            try:
                block = ResponseContentBlock.model_validate(raw_block)
            except Exception as exc:
                logger.debug(
                    "response_envelope_content_block_invalid",
                    index=index,
                    error=str(exc),
                )
                continue
        else:
            continue

        if _content_block_has_value(block):
            parsed.append(block)
    return parsed


def _content_block_has_value(block: ResponseContentBlock) -> bool:
    return bool(block.text.strip() or block.title or any(item.strip() for item in block.items))


def _build_tool_events(metadata: dict[str, Any]) -> list[ResponseToolEvent]:
    raw_tool_events = metadata.get("tool_events")
    if isinstance(raw_tool_events, list):
        parsed_tool_events: list[ResponseToolEvent] = []
        for index, raw_event in enumerate(raw_tool_events):
            if isinstance(raw_event, ResponseToolEvent):
                parsed_tool_events.append(raw_event)
                continue
            if not isinstance(raw_event, dict):
                continue
            try:
                parsed_tool_events.append(ResponseToolEvent.model_validate(raw_event))
            except Exception as exc:
                logger.debug(
                    "response_envelope_tool_event_invalid",
                    index=index,
                    error=str(exc),
                )
                continue
        if parsed_tool_events:
            return parsed_tool_events

    tool_calls = metadata.get("tool_calls")
    if not isinstance(tool_calls, list):
        return []

    return [
        ResponseToolEvent(
            name=str(tool.get("name", "unknown")),
            status=str(tool.get("status") or "planned"),
            details=tool if isinstance(tool, dict) else {"value": str(tool)},
        )
        for tool in tool_calls
        if isinstance(tool, dict)
    ]


def _render_content_blocks(blocks: list[ResponseContentBlock]) -> str:
    rendered_blocks = [rendered for block in blocks if (rendered := _render_content_block(block))]
    return "\n\n".join(rendered_blocks).strip()


def _render_content_block(block: ResponseContentBlock) -> str:
    block_type = block.type.strip().lower()
    text = block.text.strip()
    title = (block.title or "").strip()
    items = [item.strip() for item in block.items if item.strip()]

    if block_type in {"bullet_list", "bullets", "list"}:
        lines: list[str] = []
        if title:
            lines.append(f"{title}:")
        if text:
            lines.append(text)
        lines.extend(f"• {item}" for item in items)
        return "\n".join(lines).strip()

    if block_type in {"field", "label_value"}:
        if title and text:
            return f"{title}: {text}"
        if title:
            return title
        return text

    if block_type == "title":
        return text or title

    if block_type == "hidden":
        return ""

    if title and text:
        return f"{title}: {text}"
    if text:
        return text
    if items:
        return "\n".join(f"• {item}" for item in items)
    return title


def _build_citations(metadata: dict[str, Any]) -> list[ResponseCitation]:
    raw_citations = metadata.get("citations")
    if not isinstance(raw_citations, list):
        return []

    citations: list[ResponseCitation] = []
    for index, citation in enumerate(raw_citations):
        if not isinstance(citation, dict):
            continue

        source_id = _coerce_optional_str(
            citation.get("source_id")
            or citation.get("url")
            or citation.get("label")
            or f"citation-{index}"
        )
        source_type = _coerce_optional_str(citation.get("source_type")) or "external"
        if not source_id:
            continue

        citations.append(
            ResponseCitation(
                source_id=source_id,
                source_type=source_type,
                label=_coerce_optional_str(citation.get("label")),
                excerpt=_coerce_optional_str(citation.get("excerpt")),
                timestamp=_coerce_optional_str(citation.get("timestamp")),
            )
        )

    return citations

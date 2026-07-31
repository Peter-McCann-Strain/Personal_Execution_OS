"""Tests for canonical response envelope construction."""

from src.app.core.response_envelope import build_response_envelope, render_response_envelope
from src.app.domain.models import ChatResponse, Intent, IntentType, MessageInput, Specialist


def _make_intent() -> Intent:
    return Intent(
        intent_type=IntentType.RESEARCH,
        confidence=0.9,
        specialist=Specialist.RESEARCH,
        reasoning="research request",
    )


def _make_message() -> MessageInput:
    return MessageInput(content="Research this", source="api", user_id="user-1")


def test_build_response_envelope_includes_citations_and_safety_flags():
    response = ChatResponse(
        content="Research summary",
        agent="research",
        metadata={
            "trace_id": "trace-1",
            "workflow_id": "workflow-1",
            "safety_flags": ["untrusted_external_input"],
            "citations": [
                {
                    "source_id": "https://example.com",
                    "source_type": "web_result",
                    "label": "Example",
                    "excerpt": "Key point",
                }
            ],
        },
    )

    envelope = build_response_envelope(
        response,
        message=_make_message(),
        intent=_make_intent(),
        quality=None,
    )

    assert envelope.trace_id == "trace-1"
    assert envelope.workflow_id == "workflow-1"
    assert envelope.safety_flags == ["untrusted_external_input"]
    assert len(envelope.citations) == 1
    assert envelope.citations[0].source_id == "https://example.com"
    assert envelope.citations[0].label == "Example"


def test_build_response_envelope_uses_structured_content_blocks_and_tool_events():
    response = ChatResponse(
        content="fallback",
        agent="research",
        metadata={
            "content_blocks": [
                {"type": "text", "text": "FastAPI is a strong fit here."},
                {
                    "type": "bullet_list",
                    "title": "Sources (2)",
                    "items": ["Docs: async support", "Benchmarks: low latency"],
                },
                {"type": "field", "title": "Recommendation", "text": "Use FastAPI"},
            ],
            "tool_events": [
                {
                    "name": "tavily__search",
                    "status": "executed",
                    "details": {"result_preview": "2 strong sources"},
                }
            ],
        },
    )

    envelope = build_response_envelope(
        response,
        message=_make_message(),
        intent=_make_intent(),
        quality=None,
    )

    assert [block.type for block in envelope.content_blocks] == ["text", "bullet_list", "field"]
    assert envelope.content_blocks[1].title == "Sources (2)"
    assert envelope.content_blocks[1].items == [
        "Docs: async support",
        "Benchmarks: low latency",
    ]
    assert envelope.content_blocks[2].text == "Use FastAPI"
    assert len(envelope.tool_events) == 1
    assert envelope.tool_events[0].status == "executed"


def test_render_response_envelope_renders_structured_blocks_for_telegram():
    response = ChatResponse(
        content="fallback",
        agent="communications",
        metadata={
            "content_blocks": [
                {"type": "text", "text": "Here's the draft."},
                {"type": "field", "title": "Subject", "text": "Re: Launch timeline"},
                {
                    "type": "bullet_list",
                    "title": "Details",
                    "items": ["Send today", "Keep it short"],
                },
            ]
        },
    )
    message = MessageInput(content="Draft an email", source="telegram", user_id="user-1")
    envelope = build_response_envelope(
        response,
        message=message,
        intent=Intent(
            intent_type=IntentType.COMMAND,
            confidence=0.9,
            specialist=Specialist.COMMUNICATIONS,
            reasoning="draft request",
        ),
        quality=None,
    )

    rendered, metrics = render_response_envelope(
        envelope,
        message=message,
        metadata=response.metadata,
    )

    assert rendered == (
        "Here's the draft.\n\n"
        "Subject: Re: Launch timeline\n\n"
        "Details:\n"
        "• Send today\n"
        "• Keep it short"
    )
    assert metrics["content_block_count"] == 3
    assert metrics["preferred_format"] == "plain_text"


def test_build_response_envelope_skips_invalid_structured_blocks_and_tool_events():
    response = ChatResponse(
        content="fallback",
        agent="research",
        metadata={
            "content_blocks": [
                {"type": "text", "text": "Keep this block."},
                {"type": "bullet_list", "items": "not-a-list"},
            ],
            "tool_events": [
                {
                    "name": "tavily__search",
                    "status": "executed",
                    "details": {"result_preview": "ok"},
                },
                {"name": "broken"},
            ],
        },
    )

    envelope = build_response_envelope(
        response,
        message=_make_message(),
        intent=_make_intent(),
        quality=None,
    )

    assert len(envelope.content_blocks) == 1
    assert envelope.content_blocks[0].text == "Keep this block."
    assert len(envelope.tool_events) == 1
    assert envelope.tool_events[0].name == "tavily__search"

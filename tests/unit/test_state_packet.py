"""Tests for structured session state packets."""

from __future__ import annotations

from types import SimpleNamespace

from src.app.domain.models import ChatResponse, SessionStatePacket, StatePacketItem


def test_build_session_state_packet_extracts_sections():
    """The packet builder should extract multiple memory sections from recent messages."""
    from src.app.core.state_packet import build_session_state_packet

    packet = build_session_state_packet(
        [
            {
                "role": "user",
                "content": "I prefer concise answers and I will send the report tomorrow.",
                "timestamp": "2026-04-09T21:00:00+00:00",
            },
            {
                "role": "user",
                "content": "We decided to ship Project Atlas on Friday.",
                "timestamp": "2026-04-09T21:05:00+00:00",
            },
            {
                "role": "user",
                "content": "Can you follow up on Alice tomorrow?",
                "timestamp": "2026-04-09T21:10:00+00:00",
            },
            {
                "role": "assistant",
                "agent": "tools",
                "content": "Tool result: scheduled follow-up draft for Alice.",
                "timestamp": "2026-04-09T21:11:00+00:00",
            },
        ],
        conversation_summary="The user is coordinating a Friday ship date.",
    )

    assert any("prefer concise answers" in item.value.lower() for item in packet.preferences)
    assert any("send the report tomorrow" in item.value.lower() for item in packet.commitments)
    assert any("decided to ship project atlas" in item.value.lower() for item in packet.decisions)
    assert any("follow up on alice" in item.value.lower() for item in packet.open_loops)
    assert any(item.value == "Project Atlas" for item in packet.active_entities)
    assert any(
        "scheduled follow-up draft" in artifact.summary.lower()
        for artifact in packet.recent_artifacts
    )


def test_build_session_state_packet_merges_previous_items():
    """Recent extraction should retain older packet items when they are not re-observed."""
    from src.app.core.state_packet import build_session_state_packet

    previous = SessionStatePacket(
        preferences=[StatePacketItem(value="I prefer summaries with bullets.")],
        conversation_summary="Older summary",
    )

    packet = build_session_state_packet(
        [
            {
                "role": "user",
                "content": "We decided to move the review to Monday.",
                "timestamp": "2026-04-09T21:20:00+00:00",
            }
        ],
        previous_packet=previous,
    )

    assert any("prefer summaries with bullets" in item.value.lower() for item in packet.preferences)
    assert any("move the review to monday" in item.value.lower() for item in packet.decisions)


def test_render_session_state_packet_is_ordered_and_budget_aware():
    """Rendering should preserve section order and drop low-priority overflow."""
    from src.app.core.state_packet import render_session_state_packet

    packet = SessionStatePacket(
        open_loops=[StatePacketItem(value="Follow up on Alice tomorrow.")],
        commitments=[StatePacketItem(value="Send the launch note.")],
        decisions=[StatePacketItem(value="Ship on Friday.")],
        facts=[StatePacketItem(value="The user works from London.")],
        conversation_summary="Summary text.",
    )

    rendered = render_session_state_packet(packet, token_budget=30)

    assert rendered.startswith("<session_state_packet>")
    assert "open_loops:" in rendered
    assert rendered.index("open_loops:") < rendered.index("commitments:")
    assert "conversation_summary:" not in rendered


def test_evaluate_state_packet_equivalence_scores_fragment_coverage():
    """Equivalence checks should score based on preserved expected fragments."""
    from src.app.core.state_packet import EquivalenceCase, evaluate_state_packet_equivalence

    case = EquivalenceCase(
        case_id="memory-1",
        packet=SessionStatePacket(
            preferences=[StatePacketItem(value="I prefer concise answers.")],
            commitments=[StatePacketItem(value="Send the report tomorrow.")],
            conversation_summary="The user is preparing a report.",
        ),
        expected_fragments=("concise answers", "report tomorrow", "preparing a report"),
    )

    score = evaluate_state_packet_equivalence(case)

    assert score == 1.0


def test_build_session_state_packet_includes_tool_call_artifacts():
    """Tool calls from the latest response should be captured as recent artifacts."""
    from src.app.core.state_packet import build_session_state_packet

    response = ChatResponse(
        content="Done",
        agent="tools",
        metadata={
            "trace_id": "trace-123",
            "tool_calls": [{"name": "google-calendar__create_event", "status": "confirmed"}],
        },
    )

    packet = build_session_state_packet(
        [{"role": "user", "content": "Schedule a review for tomorrow."}],
        response=response,
    )

    assert any(
        artifact.artifact_type == "tool_call"
        and "google-calendar__create_event" in artifact.summary
        for artifact in packet.recent_artifacts
    )


def test_merge_persisted_artifacts_enriches_state_packet():
    """Persisted artifacts should become source-backed recent artifacts in the packet."""
    from src.app.core.state_packet import merge_persisted_artifacts

    packet = SessionStatePacket(
        conversation_summary="Existing summary",
    )
    persisted = [
        SimpleNamespace(
            artifact_type="tool_summary",
            summary="Search indexing completed and deployment shipped.",
            scope="session",
            source_id="artifact-1",
            trace_id="trace-1",
            created_at=packet.updated_at,
        ),
    ]

    merged = merge_persisted_artifacts(packet, persisted)

    assert merged is not None
    assert any(
        artifact.artifact_type == "tool_summary"
        and "search indexing completed" in artifact.summary.lower()
        and artifact.sources[0].source_id == "artifact-1"
        for artifact in merged.recent_artifacts
    )


def test_merge_persisted_artifacts_derives_structured_state_from_research_and_triage():
    """Structured persisted artifacts should enrich facts, decisions, loops, and entities."""
    from src.app.core.state_packet import merge_persisted_artifacts

    packet = SessionStatePacket(conversation_summary="Existing summary")
    created_at = packet.updated_at
    persisted = [
        SimpleNamespace(
            artifact_type="research_report",
            summary="Research: Hosted vector search options",
            scope="session",
            source_id="research-1",
            trace_id="trace-r1",
            created_at=created_at,
            payload={
                "title": "Research: Hosted vector search options",
                "key_takeaway": "Pgvector is the strongest default for this stack.",
                "recommendation": "Use Pgvector first unless recall quality clearly fails.",
                "citations": [
                    {
                        "label": "Claude Code",
                        "excerpt": "Claude Code works well with Pgvector and Redis.",
                    }
                ],
            },
        ),
        SimpleNamespace(
            artifact_type="email_triage",
            summary="Alice needs an updated deployment timeline.",
            scope="session",
            source_id="email-1",
            trace_id="trace-e1",
            created_at=created_at,
            payload={
                "classification": "ACTION_REQUIRED",
                "sender": "Alice Chen",
                "subject_summary": "Deployment timeline update",
                "suggested_action": "Reply with the revised deployment timeline",
                "response_deadline": "today 5pm",
            },
        ),
    ]

    merged = merge_persisted_artifacts(packet, persisted)

    assert merged is not None
    assert any("pgvector is the strongest default" in item.value.lower() for item in merged.facts)
    assert any("use pgvector first" in item.value.lower() for item in merged.decisions)
    assert any(
        "reply with the revised deployment timeline" in item.value.lower()
        for item in merged.open_loops
    )
    assert any("today 5pm" in item.value.lower() for item in merged.commitments)
    assert any(item.value == "Pgvector" for item in merged.active_entities)
    assert any(item.value == "Claude Code" for item in merged.active_entities)
    assert any(item.value == "Alice Chen" for item in merged.active_entities)


def test_merge_persisted_artifacts_derives_state_from_response_envelope_and_tool_summary():
    """Structured response envelopes and tool summaries should enrich recall state."""
    from src.app.core.state_packet import merge_persisted_artifacts

    packet = SessionStatePacket(conversation_summary="Existing summary")
    created_at = packet.updated_at
    persisted = [
        SimpleNamespace(
            artifact_type="response_envelope",
            summary="Assistant response about deployment follow-up.",
            scope="session",
            source_id="resp-1",
            trace_id="trace-r1",
            created_at=created_at,
            payload={
                "content_blocks": [
                    {"type": "field", "title": "Recommendation", "text": "Use FastAPI first."},
                    {
                        "type": "bullet_list",
                        "title": "Details",
                        "items": [
                            "Next step: Reply with the revised deployment timeline",
                            "Deadline: today 5pm",
                        ],
                    },
                ],
                "citations": [
                    {
                        "label": "Alice Chen",
                        "excerpt": "Alice needs the deployment timeline update.",
                    }
                ],
                "tool_events": [
                    {"name": "google-calendar__create_event", "status": "planned"},
                ],
            },
        ),
        SimpleNamespace(
            artifact_type="tool_summary",
            summary="Calendar action summary",
            scope="session",
            source_id="tool-1",
            trace_id="trace-t1",
            created_at=created_at,
            payload={
                "tool_calls": [
                    {"name": "filesystem__read_file", "status": "executed"},
                    {"name": "google-calendar__create_event", "status": "planned"},
                ],
                "tool_count": 2,
                "errors": 0,
            },
        ),
    ]

    merged = merge_persisted_artifacts(packet, persisted)

    assert merged is not None
    assert any("use fastapi first" in item.value.lower() for item in merged.decisions)
    assert any(
        "reply with the revised deployment timeline" in item.value.lower()
        for item in merged.open_loops
    )
    assert any("deadline: today 5pm" in item.value.lower() for item in merged.commitments)
    assert any(
        "pending tool action: google-calendar__create_event" in item.value.lower()
        for item in merged.open_loops
    )
    assert any(
        "executed tool: filesystem__read_file" in item.value.lower() for item in merged.facts
    )
    assert any(item.value == "Alice Chen" for item in merged.active_entities)


def test_merge_persisted_artifacts_uses_compacted_preserved_payload_fields():
    """Compacted artifact payloads should still enrich state from preserved fields."""
    from src.app.core.state_packet import merge_persisted_artifacts

    packet = SessionStatePacket(conversation_summary="Existing summary")
    created_at = packet.updated_at
    persisted = [
        SimpleNamespace(
            artifact_type="response_envelope",
            summary="Compacted envelope",
            scope="session",
            source_id="resp-compact",
            trace_id="trace-compact",
            created_at=created_at,
            payload={
                "_compacted_by": "session_maintenance_v1",
                "preserved": {
                    "content_preview": "Recommendation: Use Pgvector first. Next step: Reply with the rollout plan. Deadline: Friday 5pm.",
                    "citation_labels": ["Project Atlas"],
                    "tool_names": ["google-calendar__create_event"],
                    "tool_statuses": ["planned"],
                },
            },
        ),
        SimpleNamespace(
            artifact_type="tool_summary",
            summary="Compacted tool summary",
            scope="session",
            source_id="tool-compact",
            trace_id="trace-tool-compact",
            created_at=created_at,
            payload={
                "_compacted_by": "session_maintenance_v1",
                "preserved": {
                    "tool_names": ["filesystem__read_file"],
                    "tool_statuses": ["executed"],
                    "tool_count": 1,
                },
            },
        ),
    ]

    merged = merge_persisted_artifacts(packet, persisted)

    assert merged is not None
    assert any("use pgvector first" in item.value.lower() for item in merged.decisions)
    assert any("reply with the rollout plan" in item.value.lower() for item in merged.open_loops)
    assert any("deadline: friday 5pm" in item.value.lower() for item in merged.commitments)
    assert any(
        "pending tool action: google-calendar__create_event" in item.value.lower()
        for item in merged.open_loops
    )
    assert any(
        "executed tool: filesystem__read_file" in item.value.lower() for item in merged.facts
    )
    assert any(item.value == "Project Atlas" for item in merged.active_entities)


def test_normalized_artifact_payload_normalizes_runtime_mapping_keys():
    """Persisted JSON-like mappings should expose a stable string-key contract."""
    from src.app.core.state_packet import _normalized_artifact_payload

    assert _normalized_artifact_payload({1: "value", "title": "Report"}) == {
        "1": "value",
        "title": "Report",
    }
    assert _normalized_artifact_payload(
        {
            "_compacted_by": "session_maintenance_v1",
            "preserved": {2: "preserved"},
        }
    ) == {"2": "preserved"}


def test_build_session_state_packet_filters_non_entity_fillers_and_dates():
    """Entity extraction should keep salient names and drop obvious junk phrases."""
    from src.app.core.state_packet import build_session_state_packet

    packet = build_session_state_packet(
        [
            {
                "role": "user",
                "content": (
                    "Nothing stored about that yet. Yesterday was Thursday April 9th. "
                    "Good evening. I shipped FastAPI with Redis, Claude Code, and Project Atlas."
                ),
                "timestamp": "2026-04-10T20:00:00+00:00",
            }
        ],
    )

    values = {item.value for item in packet.active_entities}

    assert "FastAPI" in values
    assert "Redis" in values
    assert "Claude Code" in values
    assert "Project Atlas" in values
    assert "Nothing" not in values
    assert "Yesterday" not in values
    assert "Thursday April" not in values
    assert "Good" not in values

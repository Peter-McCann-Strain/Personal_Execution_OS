"""Tests for deterministic conversation-continuity resolution."""

from __future__ import annotations

from types import SimpleNamespace

from src.app.core.conversation_actions import resolve_conversation_continuity
from src.app.domain.models import MessageInput, PendingConversationAction


def _message(content: str) -> MessageInput:
    return MessageInput(content=content, source="test", user_id="user-1")


def _artifact(action: PendingConversationAction) -> SimpleNamespace:
    return SimpleNamespace(
        artifact_type="conversation_action",
        payload=action.model_dump(mode="json"),
    )


def _action(
    *,
    action_id: str,
    action_type: str,
    status: str,
    retryable: bool = True,
    specialist: str = "save",
    human_summary: str = "summary",
    normalized_payload: dict | None = None,
) -> PendingConversationAction:
    return PendingConversationAction(
        action_id=action_id,
        action_type=action_type,
        status=status,
        human_summary=human_summary,
        normalized_payload=normalized_payload or {},
        idempotency_key=f"{action_type}:{action_id}",
        retryable=retryable,
        specialist=specialist,
    )


def test_retry_reuses_recent_failed_artifact_when_pending_action_missing():
    failed_action = _action(
        action_id="failed-note",
        action_type="save_note",
        status="failed",
        normalized_payload={"note_payload": "Graph notes system"},
    )

    resolution = resolve_conversation_continuity(
        _message("try again"),
        pending_action=None,
        recent_artifacts=[_artifact(failed_action)],
    )

    assert resolution.forced_intent is not None
    assert str(resolution.forced_intent.specialist) == "save"
    assert resolution.message.metadata["continuity_resolution"]["type"] == "retry_recent_artifact"
    assert resolution.matched_action is not None
    assert resolution.matched_action.action_id == "failed-note"


def test_retry_clarifies_when_multiple_recent_failures_exist():
    failed_note = _action(
        action_id="failed-note",
        action_type="save_note",
        status="failed",
        human_summary="retry note save",
    )
    failed_project = _action(
        action_id="failed-project",
        action_type="project_draft_create",
        status="failed",
        specialist="project",
        human_summary="retry project draft",
    )

    resolution = resolve_conversation_continuity(
        _message("retry"),
        pending_action=None,
        recent_artifacts=[_artifact(failed_note), _artifact(failed_project)],
    )

    assert resolution.early_response is not None
    assert (
        resolution.early_response.metadata["continuity_resolution"]["type"]
        == "ambiguous_retry_request"
    )
    assert resolution.early_response.metadata["clarification_requested"] is True
    assert "Which one should I retry" in resolution.early_response.content


def test_note_reference_clarifies_when_both_is_underspecified():
    recent_note = _action(
        action_id="recent-note",
        action_type="save_note",
        status="succeeded",
        human_summary="saved note",
        normalized_payload={"note_payload": "Graph notes system"},
    )

    resolution = resolve_conversation_continuity(
        _message("both are now in notes"),
        pending_action=None,
        recent_artifacts=[_artifact(recent_note)],
    )

    assert resolution.early_response is not None
    assert (
        resolution.early_response.metadata["continuity_resolution"]["type"]
        == "ambiguous_note_reference"
    )
    assert resolution.early_response.metadata["clarification_requested"] is True
    assert "one recent saved note" in resolution.early_response.content

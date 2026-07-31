"""Conversation-continuity helpers for assistant-native retries and references."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from hashlib import blake2s

from src.app.domain.models import (
    ChatResponse,
    Intent,
    IntentType,
    MessageInput,
    PendingConversationAction,
    Specialist,
)

_RETRY_MARKERS = (
    "try again",
    "retry",
    "run it again",
    "do that again",
    "please retry",
)
_REFERENCE_MARKERS = {"that", "it", "those", "them", "both"}
_SAVE_ACTION_TYPES = {"save_note", "save_url"}
_FAILED_ACTION_STATUSES = {"failed"}
_SUCCEEDED_ACTION_STATUSES = {"succeeded"}


@dataclass(slots=True)
class ContinuityResolution:
    """Deterministic continuity outcome before normal routing."""

    message: MessageInput
    forced_intent: Intent | None = None
    early_response: ChatResponse | None = None
    matched_action: PendingConversationAction | None = None


def conversation_action_idempotency_key(
    action_type: str,
    payload: dict,
) -> str:
    """Build a stable idempotency key for assistant-native actions."""
    digest = blake2s(digest_size=16)
    digest.update(action_type.encode("utf-8"))
    for key in sorted(payload):
        digest.update(key.encode("utf-8"))
        digest.update(str(payload[key]).encode("utf-8"))
    return f"{action_type}:{digest.hexdigest()}"


def is_retry_request(content: str) -> bool:
    lowered = " ".join(content.casefold().split())
    return any(marker in lowered for marker in _RETRY_MARKERS)


def resolve_conversation_continuity(
    message: MessageInput,
    *,
    pending_action: PendingConversationAction | None,
    recent_artifacts: list[object] | None,
) -> ContinuityResolution:
    """Resolve retry and simple note-reference requests before routing."""
    if is_retry_request(message.content):
        return _resolve_retry_request(
            message,
            pending_action=pending_action,
            recent_artifacts=recent_artifacts or [],
        )

    note_reference_resolution = _resolve_note_reference(message, recent_artifacts or [])
    if note_reference_resolution is not None:
        return note_reference_resolution

    return ContinuityResolution(message=message)


def _resolve_retry_request(
    message: MessageInput,
    *,
    pending_action: PendingConversationAction | None,
    recent_artifacts: list[object],
) -> ContinuityResolution:
    if pending_action is not None and pending_action.retryable:
        return _retry_resolution_from_action(
            message,
            action=pending_action,
            resolution_type="retry_pending_action",
            reasoning="Retrying the most recent assistant-native action.",
        )

    failed_actions = _recent_actions_with_status(
        recent_artifacts,
        allowed_statuses=_FAILED_ACTION_STATUSES,
    )
    if len(failed_actions) == 1:
        return _retry_resolution_from_action(
            message,
            action=failed_actions[0],
            resolution_type="retry_recent_artifact",
            reasoning="Retrying the most recent persisted failed assistant-native action.",
        )
    if len(failed_actions) > 1:
        choices = _summarize_actions(failed_actions[:2])
        return ContinuityResolution(
            message=message,
            early_response=ChatResponse(
                content=(
                    f"I have multiple recent failed actions. Which one should I retry: {choices}?"
                ),
                agent="save",
                metadata={
                    "clarification_requested": True,
                    "continuity_resolution": {
                        "type": "ambiguous_retry_request",
                        "candidate_action_ids": [action.action_id for action in failed_actions[:3]],
                    },
                },
            ),
        )

    completed_action = _latest_completed_action(recent_artifacts)
    if completed_action is not None:
        receipt = completed_action.receipt_text or completed_action.human_summary
        return ContinuityResolution(
            message=message,
            early_response=ChatResponse(
                content=(f"That action has already completed. Last receipt: {receipt}"),
                agent=completed_action.specialist or "save",
                metadata={
                    "continuity_resolution": {
                        "type": "already_completed_action",
                        "action_id": completed_action.action_id,
                        "action_type": completed_action.action_type,
                    }
                },
            ),
            matched_action=completed_action,
        )

    return ContinuityResolution(
        message=message,
        early_response=ChatResponse(
            content=(
                "I don't have a recent failed action to retry. Tell me what you want me to rerun."
            ),
            agent="save",
            metadata={
                "clarification_requested": True,
                "continuity_resolution": {"type": "missing_retry_target"},
            },
        ),
    )


def _resolve_note_reference(
    message: MessageInput,
    recent_artifacts: list[object],
) -> ContinuityResolution | None:
    lowered = " ".join(message.content.casefold().split())
    lowered_tokens = set(lowered.split())
    if "notes" not in lowered and "nots" not in lowered and "nltes" not in lowered:
        return None
    if not any(marker in lowered_tokens for marker in _REFERENCE_MARKERS):
        return None

    completed = [
        action
        for action in (_artifact_to_action(artifact) for artifact in recent_artifacts)
        if (
            action is not None
            and action.action_type in _SAVE_ACTION_TYPES
            and action.status in _SUCCEEDED_ACTION_STATUSES
        )
    ]
    if "both" in lowered_tokens:
        if len(completed) < 2:
            return ContinuityResolution(
                message=message,
                early_response=ChatResponse(
                    content=(
                        "I only have one recent saved note, so I can't tell what 'both' refers to. "
                        "Say 'add that to notes' for the latest note, "
                        "or paste the two notes explicitly."
                    ),
                    agent="save",
                    metadata={
                        "clarification_requested": True,
                        "continuity_resolution": {"type": "ambiguous_note_reference"},
                    },
                ),
            )
        parts = [
            str(action.normalized_payload.get("note_payload", "")).strip()
            for action in completed[:2]
            if str(action.normalized_payload.get("note_payload", "")).strip()
        ]
        replacement = "\n".join(f"- {part}" for part in parts if part)
        latest = completed[0]
    else:
        if not completed:
            return ContinuityResolution(
                message=message,
                early_response=ChatResponse(
                    content=(
                        "I don't have a recent saved note to anchor that reference to. "
                        "Paste the note text and I'll save it directly."
                    ),
                    agent="save",
                    metadata={
                        "clarification_requested": True,
                        "continuity_resolution": {"type": "ambiguous_note_reference"},
                    },
                ),
            )
        latest = completed[0]
        replacement = latest.normalized_payload.get("note_payload")

    if not isinstance(replacement, str) or not replacement.strip():
        return ContinuityResolution(
            message=message,
            early_response=ChatResponse(
                content=(
                    "I found the recent note action, but it didn't include reusable note text. "
                    "Paste the note text and I'll save it."
                ),
                agent="save",
                metadata={
                    "clarification_requested": True,
                    "continuity_resolution": {"type": "ambiguous_note_reference"},
                },
            ),
        )

    rewritten_content = f"save this to notes: {replacement.strip()}"
    rewritten = message.model_copy(
        update={
            "content": rewritten_content,
            "metadata": {
                **message.metadata,
                "continuity_resolution": {
                    "type": "resolved_note_reference",
                    "source_action_id": latest.action_id,
                },
                "resolved_note_reference": replacement.strip(),
            },
        }
    )
    return ContinuityResolution(
        message=rewritten,
        forced_intent=Intent(
            intent_type=IntentType.SAVE,
            confidence=1.0,
            specialist=Specialist.SAVE,
            reasoning="Resolved a note reference against recent assistant-native save actions.",
        ),
        matched_action=latest,
    )


def _latest_completed_action(recent_artifacts: list[object]) -> PendingConversationAction | None:
    for artifact in recent_artifacts:
        action = _artifact_to_action(artifact)
        if action is not None and action.retryable and action.status in _SUCCEEDED_ACTION_STATUSES:
            return action
    return None


def _recent_actions_with_status(
    recent_artifacts: list[object],
    *,
    allowed_statuses: set[str],
) -> list[PendingConversationAction]:
    actions: list[PendingConversationAction] = []
    for artifact in recent_artifacts:
        action = _artifact_to_action(artifact)
        if action is None or not action.retryable or action.status not in allowed_statuses:
            continue
        actions.append(action)
    return actions


def _artifact_to_action(artifact: object) -> PendingConversationAction | None:
    artifact_type = getattr(artifact, "artifact_type", None)
    if artifact_type != "conversation_action":
        return None
    payload = getattr(artifact, "payload", None)
    if not isinstance(payload, dict):
        return None
    try:
        return PendingConversationAction.model_validate(payload)
    except Exception:
        return None


def _retry_resolution_from_action(
    message: MessageInput,
    *,
    action: PendingConversationAction,
    resolution_type: str,
    reasoning: str,
) -> ContinuityResolution:
    specialist = _specialist_for_action(action)
    rewritten = message.model_copy(
        update={
            "metadata": {
                **message.metadata,
                "pending_conversation_action": action.model_dump(mode="json"),
                "continuity_resolution": {
                    "type": resolution_type,
                    "action_id": action.action_id,
                    "action_type": action.action_type,
                },
            }
        }
    )
    return ContinuityResolution(
        message=rewritten,
        forced_intent=Intent(
            intent_type=IntentType.COMMAND,
            confidence=1.0,
            specialist=specialist,
            reasoning=reasoning,
        ),
        matched_action=action,
    )


def _specialist_for_action(action: PendingConversationAction) -> Specialist:
    if action.specialist:
        with contextlib.suppress(Exception):
            return Specialist(action.specialist)
    if action.action_type.startswith("project"):
        return Specialist.PROJECT
    return Specialist.SAVE


def _summarize_actions(actions: list[PendingConversationAction]) -> str:
    summaries: list[str] = []
    for action in actions:
        summary = action.human_summary.strip() or action.action_type
        summaries.append(summary[:80])
    if not summaries:
        return "the recent actions"
    if len(summaries) == 1:
        return summaries[0]
    return f"{summaries[0]} or {summaries[1]}"

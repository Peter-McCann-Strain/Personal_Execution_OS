"""Tests for the Socratic tutorial state module."""

from __future__ import annotations

from src.app.agents.socratic.state import (
    AgentResponse,
    BloomLevel,
    CognitiveLoad,
    EmotionalState,
    TutorialPhase,
    WorkType,
    _merge_assessor_log,
    _merge_dialogue,
    make_initial_state,
)


def test_merge_dialogue_appends_in_order() -> None:
    """Dialogue turns should be appended in arrival order."""
    existing = [{"role": "user", "content": "first"}]
    new = [{"role": "tutor", "content": "second"}]

    merged = _merge_dialogue(existing, new)

    assert merged == [
        {"role": "user", "content": "first"},
        {"role": "tutor", "content": "second"},
    ]
    assert merged is not existing
    assert merged is not new


def test_merge_assessor_log_appends_in_order() -> None:
    """Assessor log entries should be appended in arrival order."""
    existing = [{"action": "tutor"}]
    new = [{"action": "clarifier"}]

    merged = _merge_assessor_log(existing, new)

    assert merged == [{"action": "tutor"}, {"action": "clarifier"}]
    assert merged is not existing
    assert merged is not new


def test_make_initial_state_uses_sane_defaults() -> None:
    """Initial state should populate the expected defaults."""
    state = make_initial_state(
        session_id="session-1",
        user_id="user-1",
        topic="Caching",
        submitted_work="My essay",
    )

    assert state["session_id"] == "session-1"
    assert state["user_id"] == "user-1"
    assert state["topic"] == "Caching"
    assert state["submitted_work"] == "My essay"
    assert state["work_type"] == WorkType.OTHER
    assert state["phase"] == TutorialPhase.SUBMITTED
    assert state["propositions"] == []
    assert state["dialogue_history"] == []
    assert state["assessor_log"] == []
    assert state["bloom_level"] == BloomLevel.UNDERSTAND
    assert state["cognitive_load"] == CognitiveLoad.MODERATE
    assert state["emotional_state"] == EmotionalState.CURIOUS
    assert state["analysis"] is None
    assert state["error"] is None


def test_make_initial_state_accepts_overrides() -> None:
    """Initial state should preserve injected dependencies and explicit work types."""
    client = object()
    db_session = object()
    embeddings = object()

    state = make_initial_state(
        session_id="session-2",
        user_id="user-2",
        topic="Argument",
        submitted_work="My argument",
        work_type=WorkType.ARGUMENT,
        client=client,
        db_session=db_session,
        embeddings=embeddings,
    )

    assert state["work_type"] == WorkType.ARGUMENT
    assert state["client"] is client
    assert state["db_session"] is db_session
    assert state["embeddings"] is embeddings


def test_agent_response_truncates_at_sentence_boundary() -> None:
    """Long responses should truncate at a readable sentence boundary."""
    long_text = " ".join(["word"] * 99 + ["boundary."] + ["word"] * 20)

    response = AgentResponse(content=long_text, agent="tutor")

    assert len(response.content.split()) <= 100
    assert response.content.endswith(".")


def test_agent_response_adds_ellipsis_without_sentence_boundary() -> None:
    """Long responses without punctuation should end with an ellipsis."""
    response = AgentResponse(content=" ".join(["word"] * 120), agent="tutor")

    assert len(response.content.split()) <= 100
    assert response.content.endswith("...")

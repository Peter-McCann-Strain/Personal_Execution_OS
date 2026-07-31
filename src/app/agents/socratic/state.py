"""Socratic tutorial state — the blackboard that all agents read and write.

LangGraph TypedDict state acts as the blackboard. Each agent node receives
the full state but should only read its relevant slice (enforced by prompt
design, not by the framework). The Assessor reads everything.

Pydantic models define structured outputs from each agent and phase.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, TypedDict

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TutorialPhase(StrEnum):
    """Phases of a Socratic tutorial session."""

    SUBMITTED = "submitted"  # Work received, not yet prepared
    PREPARING = "preparing"  # Async preparation in progress
    READY = "ready"  # Preparation complete, awaiting user
    OPENING = "opening"  # Tutor delivers opening question
    DIALOGUE = "dialogue"  # Active Socratic dialogue
    CLOSING = "closing"  # Synthesis and wrap-up
    ANALYSING = "analysing"  # Post-tutorial analysis running
    COMPLETE = "complete"  # Tutorial finished, analysis stored


class WorkType(StrEnum):
    """Types of submitted work the system can handle."""

    ESSAY = "essay"
    CODE = "code"
    BLOG = "blog"
    CASE_STUDY = "case_study"
    ARGUMENT = "argument"
    RESEARCH = "research"
    DESIGN = "design"
    OTHER = "other"


class QuestionType(StrEnum):
    """The 6 Socratic question types."""

    CLARIFICATION = "clarification"  # "What do you mean by...?"
    ASSUMPTIONS = "assumptions"  # "What are you assuming here?"
    EVIDENCE = "evidence"  # "What evidence supports this?"
    PERSPECTIVES = "perspectives"  # "How might someone else see this?"
    IMPLICATIONS = "implications"  # "What follows from this?"
    META = "meta"  # "Why is this question important?"


class BloomLevel(StrEnum):
    """Bloom's taxonomy levels for tracking cognitive progression."""

    REMEMBER = "remember"
    UNDERSTAND = "understand"
    APPLY = "apply"
    ANALYSE = "analyse"
    EVALUATE = "evaluate"
    CREATE = "create"


class CognitiveLoad(StrEnum):
    """Estimated cognitive load of the student."""

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    OVERLOAD = "overload"


class EmotionalState(StrEnum):
    """Detected epistemic emotional state."""

    CURIOUS = "curious"
    ENGAGED = "engaged"
    CONFUSED = "confused"  # Moderate confusion is productive
    FRUSTRATED = "frustrated"  # Persistent confusion — intervene
    BORED = "bored"
    DEFENSIVE = "defensive"
    EXCITED = "excited"


class AssessorAction(StrEnum):
    """What the Assessor decides to do after each user turn."""

    TUTOR = "tutor"
    DEVILS_ADVOCATE = "devils_advocate"
    CLARIFIER = "clarifier"
    CONNECTOR = "connector"
    NO_INTERVENTION = "no_intervention"  # First-class pedagogical action
    CLOSING = "closing"  # Time to wrap up


# ---------------------------------------------------------------------------
# Pydantic models — structured outputs from agents and phases
# ---------------------------------------------------------------------------


class Proposition(BaseModel):
    """An atomic claim extracted from the submitted work."""

    index: int
    text: str
    source_location: str = ""  # e.g. "paragraph 3", "function calculate_total"
    claim_type: str = "assertion"  # assertion, assumption, conclusion, definition
    centrality: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="How central this claim is to the overall argument",
    )


class TutorPrep(BaseModel):
    """Tutor's preparation — questioning plan for the tutorial."""

    opening_question: str
    key_areas: list[str] = Field(default_factory=list)
    question_sequence: list[dict[str, str]] = Field(
        default_factory=list,
        description="Planned questions: [{question_type, target_proposition, question}]",
    )
    work_summary: str = ""


class DevilsAdvocatePrep(BaseModel):
    """Devil's Advocate's preparation — counter-arguments and steelman positions."""

    counter_arguments: list[dict[str, Any]] = Field(
        default_factory=list,
        description="[{proposition_index, counter, strength, source}]",
    )
    steelman_positions: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Strengthened versions of weak arguments",
    )
    vulnerabilities: list[str] = Field(default_factory=list)


class ClarifierPrep(BaseModel):
    """Clarifier's preparation — ambiguity and vagueness detection."""

    ambiguous_terms: list[dict[str, str]] = Field(
        default_factory=list,
        description="[{term, context, why_ambiguous}]",
    )
    vague_claims: list[dict[str, str]] = Field(
        default_factory=list,
        description="[{claim, what_needs_specification}]",
    )
    undefined_concepts: list[str] = Field(default_factory=list)


class ConnectorPrep(BaseModel):
    """Connector's preparation — links to the user's second brain."""

    relevant_notes: list[dict[str, str]] = Field(
        default_factory=list,
        description="[{title, summary, relevance}]",
    )
    prior_work_links: list[dict[str, str]] = Field(
        default_factory=list,
        description="[{topic, connection, source}]",
    )
    knowledge_gaps: list[str] = Field(default_factory=list)


class AssessorDecision(BaseModel):
    """Assessor's hidden routing decision after each user turn."""

    action: AssessorAction
    reasoning: str  # Hidden from user — stored in blackboard
    bloom_level: BloomLevel = BloomLevel.UNDERSTAND
    cognitive_load: CognitiveLoad = CognitiveLoad.MODERATE
    emotional_state: EmotionalState = EmotionalState.ENGAGED
    question_suggestion: str | None = None  # Hint for selected agent
    should_advance_proposition: bool = False  # Move to next claim?
    speaking_ratio_ok: bool = True  # Is user talking enough?


class AgentResponse(BaseModel):
    """What an agent says to the user during the dialogue."""

    content: str  # The actual response text
    agent: str  # "tutor", "devils_advocate", "clarifier", "connector"
    question_type: QuestionType | None = None
    think: str = ""  # Hidden reasoning (MedTutor-R1 style, never shown to user)
    visual: dict[str, Any] | None = None  # Diagram/image for visual pane (Layer 3)

    @field_validator("content")
    @classmethod
    def enforce_length_limit(cls, v: str) -> str:
        """Truncate agent responses exceeding the word limit.

        Socratic agents should respond in 1-3 sentences (~75 words max).
        If the LLM exceeds this, truncate at the last sentence boundary
        within the limit to preserve coherence.
        """
        max_words = 100  # generous buffer above the 75-word target
        words = v.split()
        if len(words) <= max_words:
            return v
        # Truncate at last sentence boundary within limit
        truncated = " ".join(words[:max_words])
        # Find last sentence-ending punctuation
        for end in [".", "?", "!"]:
            last_idx = truncated.rfind(end)
            if last_idx > len(truncated) // 2:  # don't cut too short
                return truncated[: last_idx + 1]
        return truncated + "..."


class DialogueTurn(BaseModel):
    """A single turn in the tutorial dialogue."""

    role: str  # "user" or agent name
    content: str
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    question_type: QuestionType | None = None
    bloom_level: BloomLevel | None = None
    think: str = ""  # Hidden reasoning, never shown to user


class TutorialAnalysis(BaseModel):
    """Post-tutorial analysis output."""

    summary: str
    bloom_progression: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_gaps: list[dict[str, Any]] = Field(default_factory=list)
    strong_areas: list[dict[str, Any]] = Field(default_factory=list)
    reasoning_quality: dict[str, Any] = Field(default_factory=dict)
    engagement_metrics: dict[str, Any] = Field(default_factory=dict)
    recommendations: list[str] = Field(default_factory=list)
    unresolved_topics: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# LangGraph state — the blackboard
# ---------------------------------------------------------------------------


def _merge_dialogue(
    existing: list[dict[str, Any]],
    new: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Append new dialogue turns to existing history (reducer for LangGraph)."""
    return [*existing, *new]


def _merge_assessor_log(
    existing: list[dict[str, Any]],
    new: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Append new assessor reasoning entries."""
    return [*existing, *new]


class TutorialState(TypedDict, total=False):
    """Blackboard state for the Socratic tutorial LangGraph graph.

    Every field is optional (total=False) so nodes can return partial updates.
    LangGraph merges returned dicts into the existing state.

    Annotated fields use custom reducers for list merging.
    """

    # --- Session metadata ---
    session_id: str
    user_id: str
    topic: str
    submitted_work: str
    work_type: str  # WorkType value
    phase: str  # TutorialPhase value

    # --- Preparation results (populated by Send() fan-out) ---
    propositions: list[dict[str, Any]]
    tutor_prep: dict[str, Any]
    devils_advocate_prep: dict[str, Any]
    clarifier_prep: dict[str, Any]
    connector_prep: dict[str, Any]

    # --- Dialogue state ---
    dialogue_history: Annotated[list[dict[str, Any]], _merge_dialogue]
    current_turn: int
    current_speaker: str
    current_proposition_index: int
    propositions_explored: list[int]

    # --- Assessor state (hidden from user) ---
    assessor_log: Annotated[list[dict[str, Any]], _merge_assessor_log]
    bloom_level: str  # BloomLevel value
    speaking_ratio: dict[str, int]  # {"user_words": N, "agent_words": N}
    cognitive_load: str  # CognitiveLoad value
    emotional_state: str  # EmotionalState value
    no_intervention_count: int

    # --- Context engineering ---
    working_memory: list[dict[str, Any]]  # Last N turns verbatim
    session_summary: str  # Compressed older context

    # --- Tracking ---
    claims_resolved: list[dict[str, Any]]
    claims_unresolved: list[dict[str, Any]]
    knowledge_gaps: list[dict[str, str]]

    # --- Post-analysis ---
    analysis: dict[str, Any] | None

    # --- System (not serialised to checkpoints) ---
    client: Any  # AsyncAnthropic
    db_session: Any  # AsyncSession (optional, for second brain queries)
    embeddings: Any  # OllamaEmbeddings (optional, for vector search)
    error: str | None


# ---------------------------------------------------------------------------
# State initialisation helper
# ---------------------------------------------------------------------------


def make_initial_state(
    *,
    session_id: str,
    user_id: str,
    topic: str,
    submitted_work: str,
    work_type: str = WorkType.OTHER,
    client: Any = None,
    db_session: Any = None,
    embeddings: Any = None,
) -> TutorialState:
    """Create a fresh TutorialState with sane defaults."""
    return TutorialState(
        session_id=session_id,
        user_id=user_id,
        topic=topic,
        submitted_work=submitted_work,
        work_type=work_type,
        phase=TutorialPhase.SUBMITTED,
        propositions=[],
        tutor_prep={},
        devils_advocate_prep={},
        clarifier_prep={},
        connector_prep={},
        dialogue_history=[],
        current_turn=0,
        current_speaker="",
        current_proposition_index=0,
        propositions_explored=[],
        assessor_log=[],
        bloom_level=BloomLevel.UNDERSTAND,
        speaking_ratio={"user_words": 0, "agent_words": 0},
        cognitive_load=CognitiveLoad.MODERATE,
        emotional_state=EmotionalState.CURIOUS,
        no_intervention_count=0,
        working_memory=[],
        session_summary="",
        claims_resolved=[],
        claims_unresolved=[],
        knowledge_gaps=[],
        analysis=None,
        client=client,
        db_session=db_session,
        embeddings=embeddings,
        error=None,
    )

"""Domain models — pure Pydantic, no framework dependencies."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from src.app.domain.constants import ParaCategory


class IntentType(StrEnum):
    CAPTURE = "capture"
    QUERY = "query"
    COMMAND = "command"
    SAVE = "save"
    RESEARCH = "research"
    PROJECT = "project"
    REVIEW = "review"
    PLAN_DAY = "plan_day"
    TUTORIAL = "tutorial"
    CONVERSATIONAL = "conversational"


class Specialist(StrEnum):
    DIARY = "diary"
    MEMORY = "memory"
    RESEARCH = "research"
    REVIEW = "review"
    NOTIFICATION = "notification"
    TOOLS = "tools"
    SAVE = "save"
    PROJECT = "project"
    COMMUNICATIONS = "communications"
    PLAN_DAY = "plan_day"
    SOCRATIC = "socratic"
    CONVERSATIONAL = "conversational"


class Intent(BaseModel):
    """Classified intent from the supervisor."""

    intent_type: IntentType
    confidence: float = Field(ge=0.0, le=1.0)
    specialist: Specialist
    reasoning: str


class MessageInput(BaseModel):
    """Normalised input message from any source."""

    content: str
    source: str  # "telegram", "cli", "voice"
    user_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict = Field(default_factory=dict)


class DiaryEntry(BaseModel):
    """Structured output from the diary agent."""

    content: str
    summary: str
    user_reply: str = ""
    mood_score: float | None = Field(default=None, ge=0.0, le=10.0)
    energy_rating: float | None = Field(default=None, ge=0.0, le=10.0)
    tags: list[str] = Field(default_factory=list)
    people_mentioned: list[str] = Field(default_factory=list)
    para_category: ParaCategory | None = None
    action_item: str | None = None


class ChatResponse(BaseModel):
    """Response sent back to the user."""

    content: str
    agent: str
    metadata: dict = Field(default_factory=dict)


class ResponseQuality(BaseModel):
    """Structured runtime quality record for one response."""

    route_quality: float | None = Field(default=None, ge=0.0, le=1.0)
    context_quality: float | None = Field(default=None, ge=0.0, le=1.0)
    tool_use_quality: float | None = Field(default=None, ge=0.0, le=1.0)
    final_response_quality: float | None = Field(default=None, ge=0.0, le=1.0)
    grounding: float | None = Field(default=None, ge=0.0, le=1.0)
    channel_style: float | None = Field(default=None, ge=0.0, le=1.0)
    passes: bool = True
    issue: str = ""
    suggestion: str = ""
    evaluator_version: str = "runtime_v2"


class ResponseCitation(BaseModel):
    """Source reference attached to a response envelope."""

    source_id: str
    source_type: str
    label: str | None = None
    excerpt: str | None = None
    timestamp: str | None = None


class StatePacketSource(BaseModel):
    """Source reference retained inside compacted session memory."""

    source_id: str
    source_type: str
    timestamp: str | None = None
    excerpt: str | None = None


class StatePacketItem(BaseModel):
    """One compacted memory item with retained sources."""

    value: str
    sources: list[StatePacketSource] = Field(default_factory=list)


class StatePacketArtifact(BaseModel):
    """Recent tool or workflow artifact retained in session memory."""

    artifact_type: str
    summary: str
    scope: str = "session"
    sources: list[StatePacketSource] = Field(default_factory=list)


class SessionStatePacket(BaseModel):
    """Machine-readable compacted session state."""

    packet_version: str = "v1"
    open_loops: list[StatePacketItem] = Field(default_factory=list)
    facts: list[StatePacketItem] = Field(default_factory=list)
    preferences: list[StatePacketItem] = Field(default_factory=list)
    active_entities: list[StatePacketItem] = Field(default_factory=list)
    recent_artifacts: list[StatePacketArtifact] = Field(default_factory=list)
    commitments: list[StatePacketItem] = Field(default_factory=list)
    decisions: list[StatePacketItem] = Field(default_factory=list)
    conversation_summary: str = ""
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PendingToolCall(BaseModel):
    """Validated tool call awaiting confirmation or execution."""

    tool_use_id: str
    name: str
    input: dict = Field(default_factory=dict)
    idempotency_key: str
    audit: dict = Field(default_factory=dict)


class PendingToolPlan(BaseModel):
    """Stored mutating-tool plan that can be resumed after user confirmation."""

    plan_id: str
    original_user_message: str
    tool_calls: list[PendingToolCall] = Field(default_factory=list)
    trust_label: str
    workflow_id: str | None = None
    checkpoint_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PendingConversationAction(BaseModel):
    """Stored assistant-native action that can be retried or referenced later."""

    action_id: str
    action_type: str
    status: str
    human_summary: str
    normalized_payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str
    retryable: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    failed_at: datetime | None = None
    last_error: str | None = None
    specialist: str | None = None
    receipt_text: str | None = None
    source_message: str | None = None


class DayPlanTask(BaseModel):
    """One planned task tracked through the day."""

    title: str
    source: str = "user"
    status: str = "planned"
    rescheduled_for: str | None = None
    notes: str | None = None


class DayPlanArtifact(BaseModel):
    """Persisted daily plan artifact used by morning and evening flows."""

    source_date: str
    status: str = "active"
    focus_summary: str = ""
    plan_summary: str = ""
    plan_text: str = ""
    tasks: list[DayPlanTask] = Field(default_factory=list)
    carry_over_tasks: list[str] = Field(default_factory=list)
    previous_artifact_id: str | None = None
    created_from: str = "telegram"
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PendingPlanningSession(BaseModel):
    """Short-lived planning or closeout loop persisted in conversation context."""

    session_type: str
    source_date: str
    stage: str = "invited"
    expires_at: datetime
    last_active_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    plan_artifact_id: str | None = None
    draft_plan: DayPlanArtifact | None = None
    unresolved_tasks: list[str] = Field(default_factory=list)


class ToolSpec(BaseModel):
    """Canonical runtime contract for one tool."""

    tool_id: str
    server_name: str
    tool_name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    auth_required: bool = False
    roots: list[str] = Field(default_factory=list)
    mutation_class: str = "read_only"
    allowed_parallelism: str = "sequential"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolInvocationPlan(BaseModel):
    """Validated tool invocation ready for execution or confirmation."""

    tool_id: str
    server_name: str
    tool_name: str
    public_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    argument_hash: str
    idempotency_key: str
    trust_context: str
    requires_confirmation: bool = False
    mutation_class: str = "read_only"
    allowed_parallelism: str = "sequential"
    audit_metadata: dict[str, Any] = Field(default_factory=dict)
    workflow_id: str | None = None


class PolicyDecision(BaseModel):
    """One runtime policy decision for audit and monitoring."""

    policy_name: str
    decision: str
    reason: str
    subject_type: str
    subject_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArtifactRecord(BaseModel):
    """Typed artifact captured from a response or tool execution."""

    artifact_type: str
    scope: str = "session"
    summary: str
    source_id: str | None = None
    trace_id: str | None = None
    workflow_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ResponseAction(BaseModel):
    """User-visible or client-visible action attached to a response."""

    kind: str
    label: str
    payload: dict = Field(default_factory=dict)


class ResponseToolEvent(BaseModel):
    """Tool execution summary attached to a response envelope."""

    name: str
    status: str
    details: dict = Field(default_factory=dict)


class ResponseContentBlock(BaseModel):
    """Canonical internal content block."""

    type: str = "text"
    text: str = ""
    title: str | None = None
    items: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChannelHints(BaseModel):
    """Channel-specific delivery hints for downstream renderers."""

    preferred_format: str = "plain_text"
    prefer_chunking: bool = False
    prefer_reply_anchor: bool = False
    spoken_style: bool = False


class ResponseEnvelope(BaseModel):
    """Canonical internal response envelope used before final rendering."""

    response_id: str
    interaction_id: str | None = None
    trace_id: str | None = None
    workflow_id: str | None = None
    workflow_status: str | None = None
    specialist: str
    content_blocks: list[ResponseContentBlock] = Field(default_factory=list)
    citations: list[ResponseCitation] = Field(default_factory=list)
    actions: list[ResponseAction] = Field(default_factory=list)
    tool_events: list[ResponseToolEvent] = Field(default_factory=list)
    quality: ResponseQuality | None = None
    safety_flags: list[str] = Field(default_factory=list)
    channel_hints: ChannelHints = Field(default_factory=ChannelHints)


class WorkflowState(BaseModel):
    """High-level runtime state for one assistant workflow execution."""

    workflow_id: str
    status: str
    source: str
    user_id: str
    message_content: str
    trace_id: str | None = None
    interaction_id: str | None = None
    specialist: str | None = None
    pending_checkpoint_id: str | None = None
    flags: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)

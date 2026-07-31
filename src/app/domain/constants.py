"""Domain constants — canonical status values used across persistence and services.

All status/type literals are defined here as StrEnums. Repository validation
and service logic should reference these instead of inline string literals.
"""

from enum import StrEnum


class TaskStatus(StrEnum):
    BACKLOG = "backlog"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"
    BLOCKED = "blocked"


class ProjectStatus(StrEnum):
    PLANNING = "planning"
    IN_PROGRESS = "in-progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class CommitmentStatus(StrEnum):
    DETECTED = "detected"
    CONFIRMED = "confirmed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"


class GoalStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class EpisodeType(StrEnum):
    DIARY = "diary"
    RESEARCH = "research"
    COMMUNICATION = "communication"
    PROJECT = "project"
    NOTE = "note"
    SAVED_CONTENT = "saved_content"
    TUTORIAL = "tutorial"


class ParaCategory(StrEnum):
    PROJECT = "project"
    AREA = "area"
    RESOURCE = "resource"
    ARCHIVE = "archive"


class NotificationPriority(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class NotificationStatus(StrEnum):
    UNREAD = "unread"
    READ = "read"
    DISMISSED = "dismissed"
    PENDING = "pending"


class NotificationCategory(StrEnum):
    DEADLINE = "deadline"
    COMMITMENT = "commitment"
    RELATIONSHIP = "relationship"
    SYSTEM = "system"
    DIGEST = "digest"
    PROACTIVE = "proactive"
    TUTORIAL = "tutorial"


class VoiceCallDirection(StrEnum):
    OUTBOUND = "outbound"
    INBOUND = "inbound"


class VoiceSessionChannel(StrEnum):
    PSTN_OUTBOUND = "pstn_outbound"
    PSTN_INBOUND = "pstn_inbound"
    APP_REALTIME = "app_realtime"


class VoiceSessionPurpose(StrEnum):
    SCHEDULED_REFLECTION = "scheduled_reflection"
    ON_DEMAND_REFLECTION = "on_demand_reflection"
    GENERAL_ASSISTANT = "general_assistant"


class VoiceCallTriggerSource(StrEnum):
    MANUAL_TEST = "manual_test"
    SCHEDULED_REFLECTION = "scheduled_reflection"
    ON_DEMAND_REFLECTION = "on_demand_reflection"
    INBOUND_CALL = "inbound_call"
    APP_SESSION = "app_session"


class VoiceCallStatus(StrEnum):
    QUEUED = "queued"
    INITIATED = "initiated"
    COMPLETED = "completed"
    FAILED = "failed"
    NO_ANSWER = "no_answer"
    BUSY = "busy"


class VoiceProcessingStatus(StrEnum):
    PENDING = "pending"
    TRANSCRIPT_RECEIVED = "transcript_received"
    INGESTED = "ingested"
    FAILED = "failed"


# Sets for common validation checks
OPEN_COMMITMENT_STATUSES = frozenset(
    {
        CommitmentStatus.DETECTED,
        CommitmentStatus.CONFIRMED,
        CommitmentStatus.IN_PROGRESS,
    }
)

CLOSED_COMMITMENT_STATUSES = frozenset(
    {
        CommitmentStatus.COMPLETED,
        CommitmentStatus.CANCELLED,
    }
)


class EvalStatus(StrEnum):
    """Evaluation lifecycle for InteractionRecords."""

    PENDING = "pending"
    AUTO_SCORED = "auto_scored"
    DEEP_SCORED = "deep_scored"
    SKIPPED = "skipped"


class FeedbackRating(StrEnum):
    """User feedback via Telegram inline keyboard."""

    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"


class TraceSpanKind(StrEnum):
    """Canonical runtime span kinds for request tracing."""

    REQUEST = "request"
    ROUTING = "routing"
    CONTEXT = "context"
    SPECIALIST = "specialist"
    TOOL = "tool"
    EVALUATION = "evaluation"
    RENDER = "render"
    DELIVERY = "delivery"
    PERSISTENCE = "persistence"


class TraceSpanStatus(StrEnum):
    """Status of a traced runtime span."""

    SUCCESS = "success"
    DEGRADED = "degraded"
    ERROR = "error"


class WorkflowStatus(StrEnum):
    """Lifecycle state for a workflow-backed interaction."""

    RUNNING = "running"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    DEGRADED = "degraded"
    FAILED = "failed"
    SHADOW = "shadow"


class ToolMutationClass(StrEnum):
    """Whether a tool changes state outside the assistant."""

    READ_ONLY = "read_only"
    MUTATING = "mutating"


class ToolParallelism(StrEnum):
    """Execution strategy allowed for a tool invocation."""

    SEQUENTIAL = "sequential"
    PARALLEL_READ_ONLY = "parallel_read_only"


class PolicyDecisionOutcome(StrEnum):
    """Runtime policy outcomes for tool and trust decisions."""

    ALLOW = "allow"
    REQUIRE_CONFIRMATION = "require_confirmation"
    DENY = "deny"
    DEGRADED = "degraded"


class TrustLabel(StrEnum):
    """Trust boundary labels for inbound content and tool outputs."""

    TRUSTED_SYSTEM = "trusted_system"
    TRUSTED_USER = "trusted_user"
    UNTRUSTED_EXTERNAL = "untrusted_external"

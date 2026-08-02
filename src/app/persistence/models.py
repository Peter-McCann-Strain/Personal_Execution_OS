"""Compatibility facade for all SQLAlchemy persistence models.

Domain declarations live in ``model_defs``. Importing this module loads every
declaration into the shared registry so existing imports and Alembic metadata
discovery continue to work unchanged.
"""

from src.app.persistence.model_defs.base import (
    DEFAULT_ACCOUNT_ID,
    DEFAULT_OWNER_USER_ID,
    AccountScopedMixin,
    Base,
    SoftDeleteMixin,
    not_deleted,
)
from src.app.persistence.model_defs.connectors import (
    ConnectorAccount,
    ConnectorDocument,
    ConnectorOAuthState,
    ConnectorSyncJob,
    ScheduledAction,
    ScheduledActionRun,
)
from src.app.persistence.model_defs.memory import (
    Entity,
    EntityMention,
    EntityRelationship,
    Episode,
    Goal,
    Note,
    NoteLink,
)
from src.app.persistence.model_defs.notifications import (
    NotificationRecord,
    WebPushSubscription,
)
from src.app.persistence.model_defs.observability import (
    AgentAction,
    AgentTraceSpan,
    InteractionRecord,
    PolicyDecisionRecord,
    ToolReceipt,
)
from src.app.persistence.model_defs.operations import (
    DLQJob,
    IdempotencyKey,
    IssueDedup,
)
from src.app.persistence.model_defs.people import (
    Contact,
    Interaction,
)
from src.app.persistence.model_defs.planning import (
    Commitment,
    Decision,
    Habit,
    HabitLog,
    Review,
)
from src.app.persistence.model_defs.platform import (
    Account,
    AccountMembership,
    AuditEvent,
    DataExport,
    DeletionRequest,
    Entitlement,
    LocalAuthSession,
    LocalOwnerCredential,
    UsageMetering,
    User,
)
from src.app.persistence.model_defs.projects import (
    ContentAsset,
    Epic,
    Milestone,
    NoteCanvas,
    Project,
    ProjectDraft,
    SavedMemory,
    Task,
    TaskDependency,
)
from src.app.persistence.model_defs.voice import (
    TutorialSession,
    VoiceCall,
)
from src.app.persistence.model_defs.workflows import (
    ApprovalRequest,
    ArtifactRecordModel,
    BrowserSession,
    WorkflowCheckpoint,
    WorkflowRun,
    WorkflowRunStep,
)

__all__ = (
    "DEFAULT_ACCOUNT_ID",
    "DEFAULT_OWNER_USER_ID",
    "Account",
    "AccountMembership",
    "AccountScopedMixin",
    "AgentAction",
    "AgentTraceSpan",
    "ApprovalRequest",
    "ArtifactRecordModel",
    "AuditEvent",
    "Base",
    "BrowserSession",
    "Commitment",
    "ConnectorAccount",
    "ConnectorDocument",
    "ConnectorOAuthState",
    "ConnectorSyncJob",
    "Contact",
    "ContentAsset",
    "DLQJob",
    "DataExport",
    "Decision",
    "DeletionRequest",
    "Entitlement",
    "Entity",
    "EntityMention",
    "EntityRelationship",
    "Epic",
    "Episode",
    "Goal",
    "Habit",
    "HabitLog",
    "IdempotencyKey",
    "Interaction",
    "InteractionRecord",
    "IssueDedup",
    "LocalAuthSession",
    "LocalOwnerCredential",
    "Milestone",
    "Note",
    "NoteCanvas",
    "NoteLink",
    "NotificationRecord",
    "PolicyDecisionRecord",
    "Project",
    "ProjectDraft",
    "Review",
    "SavedMemory",
    "ScheduledAction",
    "ScheduledActionRun",
    "SoftDeleteMixin",
    "Task",
    "TaskDependency",
    "ToolReceipt",
    "TutorialSession",
    "UsageMetering",
    "User",
    "VoiceCall",
    "WebPushSubscription",
    "WorkflowCheckpoint",
    "WorkflowRun",
    "WorkflowRunStep",
    "not_deleted",
)

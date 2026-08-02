"""Compatibility checks for the persistence model facade."""

import hashlib
import subprocess
import sys

from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import configure_mappers
from sqlalchemy.schema import CreateIndex, CreateTable

from src.app.persistence import models

EXPECTED_SCHEMA_FINGERPRINT = "b05d851cc486b72730adcc9d5a5b43313aae5769a223b9d7d067d6229fa1c7dc"

EXPECTED_EXPORTS = {
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
}

EXPECTED_TABLES = {
    "account_memberships",
    "accounts",
    "agent_actions",
    "agent_trace_spans",
    "approval_requests",
    "artifacts",
    "audit_events",
    "browser_sessions",
    "commitments",
    "connector_accounts",
    "connector_documents",
    "connector_oauth_states",
    "connector_sync_jobs",
    "contacts",
    "content_assets",
    "data_exports",
    "decisions",
    "deletion_requests",
    "dlq_jobs",
    "entities",
    "entitlements",
    "entity_mentions",
    "entity_relationships",
    "epics",
    "episodes",
    "goals",
    "habit_logs",
    "habits",
    "idempotency_keys",
    "interaction_records",
    "interactions",
    "issue_dedup",
    "local_auth_sessions",
    "local_owner_credentials",
    "milestones",
    "note_canvases",
    "note_links",
    "notes",
    "notifications",
    "policy_decisions",
    "project_drafts",
    "projects",
    "reviews",
    "saved_memories",
    "scheduled_action_runs",
    "scheduled_actions",
    "task_dependencies",
    "tasks",
    "tool_receipts",
    "tutorial_sessions",
    "usage_metering",
    "users",
    "voice_calls",
    "web_push_subscriptions",
    "workflow_checkpoints",
    "workflow_run_steps",
    "workflow_runs",
}

EXPECTED_RELATIONSHIPS = {
    "Contact": {"interactions": "Interaction"},
    "Entity": {
        "incoming_relationships": "EntityRelationship",
        "mentions": "EntityMention",
        "outgoing_relationships": "EntityRelationship",
    },
    "EntityMention": {"entity": "Entity", "episode": "Episode"},
    "EntityRelationship": {
        "source_entity": "Entity",
        "target_entity": "Entity",
    },
    "Epic": {"milestones": "Milestone", "project": "Project"},
    "Episode": {"entity_mentions": "EntityMention"},
    "Goal": {"children": "Goal", "parent": "Goal"},
    "Habit": {"logs": "HabitLog"},
    "HabitLog": {"habit": "Habit"},
    "Interaction": {"contact": "Contact"},
    "Milestone": {"epic": "Epic", "tasks": "Task"},
    "Note": {"incoming_links": "NoteLink", "outgoing_links": "NoteLink"},
    "NoteLink": {"source_note": "Note", "target_note": "Note"},
    "Project": {"epics": "Epic"},
    "Task": {
        "incoming_dependencies": "TaskDependency",
        "milestone": "Milestone",
        "outgoing_dependencies": "TaskDependency",
    },
    "TaskDependency": {
        "depends_on_task": "Task",
        "task": "Task",
    },
}


def test_model_facade_preserves_public_exports() -> None:
    assert set(models.__all__) == EXPECTED_EXPORTS
    assert all(hasattr(models, name) for name in EXPECTED_EXPORTS)


def test_model_facade_loads_complete_alembic_metadata() -> None:
    assert set(models.Base.metadata.tables) == EXPECTED_TABLES


def test_model_facade_configures_all_relationships() -> None:
    configure_mappers()

    actual = {
        mapper.class_.__name__: {
            relationship.key: relationship.mapper.class_.__name__
            for relationship in mapper.relationships
        }
        for mapper in models.Base.registry.mappers
        if mapper.relationships
    }

    assert actual == EXPECTED_RELATIONSHIPS


def test_model_facade_preserves_schema_and_mapper_fingerprint() -> None:
    configure_mappers()
    dialect = postgresql.dialect()
    definitions: list[str] = []

    for _, table in sorted(models.Base.metadata.tables.items()):
        definitions.append(str(CreateTable(table).compile(dialect=dialect)))
        definitions.extend(
            str(CreateIndex(index).compile(dialect=dialect))
            for index in sorted(table.indexes, key=lambda item: str(item.name))
        )

    for mapper in sorted(models.Base.registry.mappers, key=lambda item: item.class_.__name__):
        for relationship in sorted(mapper.relationships, key=lambda item: item.key):
            local_remote_pairs = ",".join(
                sorted(
                    (f"{local.table.name}.{local.name}>{remote.table.name}.{remote.name}")
                    for local, remote in (relationship.local_remote_pairs or ())
                )
            )
            definitions.append(
                "|".join(
                    (
                        mapper.class_.__name__,
                        relationship.key,
                        relationship.mapper.class_.__name__,
                        relationship.direction.name,
                        str(relationship.back_populates),
                        str(relationship.passive_deletes),
                        str(relationship.cascade),
                        local_remote_pairs,
                    )
                )
            )

    fingerprint = hashlib.sha256("\n".join(definitions).encode()).hexdigest()

    assert fingerprint == EXPECTED_SCHEMA_FINGERPRINT


def test_direct_domain_import_still_loads_complete_registry() -> None:
    program = "\n".join(
        (
            "from sqlalchemy.orm import configure_mappers",
            "from src.app.persistence.model_defs.observability import ToolReceipt",
            "from src.app.persistence.model_defs.base import Base",
            "configure_mappers()",
            "print(ToolReceipt.__tablename__, len(Base.metadata.tables), len(Base.registry.mappers))",
        )
    )

    completed = subprocess.run(
        [sys.executable, "-c", program],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout.strip() == "tool_receipts 57 57"

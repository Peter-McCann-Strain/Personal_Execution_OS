"""Pydantic schemas for validating JSONB columns before database writes.

These models ensure data integrity for columns that store LLM-generated
or application-structured JSON. Validate with model.model_validate(data)
before writing to the database.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Reviews — reviews.content JSONB
# ---------------------------------------------------------------------------


class GoalProgressItem(BaseModel):
    """A single goal's progress in a review."""

    title: str
    progress: float
    status: str


class OpenCommitmentItem(BaseModel):
    """A single commitment status in a review."""

    action: str
    status: str


class ReviewContent(BaseModel):
    """Schema for the reviews.content JSONB column."""

    accomplishments: list[str] = Field(default_factory=list)
    mood_summary: str | None = None
    average_mood: float | None = None
    average_energy: float | None = None
    goal_progress: list[GoalProgressItem] = Field(default_factory=list)
    open_commitments: list[OpenCommitmentItem] = Field(default_factory=list)
    relationship_alerts: list[str] = Field(default_factory=list)
    patterns_noticed: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    key_insight: str | None = None


# ---------------------------------------------------------------------------
# Tutorials — tutorial_sessions JSONB columns
# ---------------------------------------------------------------------------


class DialogueTurnRecord(BaseModel):
    """A single turn in a tutorial transcript."""

    role: str
    content: str
    timestamp: str | None = None
    question_type: str | None = None
    bloom_level: str | None = None
    think: str = ""


class AssessorLogEntry(BaseModel):
    """A single assessor decision log entry."""

    turn: int = 0
    action: str = ""
    reasoning: str = ""
    bloom_level: str | None = None
    cognitive_load: str | None = None
    emotional_state: str | None = None
    timestamp: str | None = None


class KnowledgeGapItem(BaseModel):
    """A knowledge gap identified during tutorial analysis."""

    gap: str
    addressed: bool = False
    recommendation: str | None = None


class TutorialAnalysisRecord(BaseModel):
    """Schema for tutorial_sessions.analysis JSONB column."""

    summary: str = ""
    bloom_progression: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_gaps: list[KnowledgeGapItem | dict[str, Any]] = Field(default_factory=list)
    strong_areas: list[dict[str, Any]] = Field(default_factory=list)
    reasoning_quality: dict[str, Any] = Field(default_factory=dict)
    engagement_metrics: dict[str, Any] = Field(default_factory=dict)
    recommendations: list[str] = Field(default_factory=list)
    unresolved_topics: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Interaction records — interaction_records.deep_scores JSONB
# ---------------------------------------------------------------------------


class DeepScores(BaseModel):
    """Schema for interaction_records.deep_scores JSONB column."""

    relevance: float | None = None
    actionability: float | None = None
    tone: float | None = None
    conciseness: float | None = None
    reasoning: str | None = None
    evaluated_at: str | None = None


# ---------------------------------------------------------------------------
# Auto-judge scores (stored inline in interaction_records)
# ---------------------------------------------------------------------------


class AutoJudgeScores(BaseModel):
    """Schema for auto-judge evaluation scores."""

    relevance: float = Field(ge=0.0, le=1.0)
    actionability: float = Field(ge=0.0, le=1.0)
    tone: float = Field(ge=0.0, le=1.0)
    conciseness: float = Field(ge=0.0, le=1.0)

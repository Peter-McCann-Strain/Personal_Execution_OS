"""Deterministic regression harness for compacted session memory."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from src.app.core.state_packet import (
    EquivalenceCase,
    build_session_state_packet,
    evaluate_state_packet_equivalence,
)
from src.app.domain.models import ChatResponse


class MemoryEquivalenceDatasetCase(BaseModel):
    """One benchmark case for state-packet preservation."""

    id: str
    messages: list[dict[str, str]] = Field(default_factory=list)
    conversation_summary: str = ""
    expected_fragments: list[str] = Field(default_factory=list)
    response_tool_calls: list[dict] = Field(default_factory=list)


class MemoryEquivalenceDataset(BaseModel):
    """Collection of benchmark sessions for compacted memory regression testing."""

    dataset_id: str
    version: str
    minimum_average_coverage: float = Field(default=0.95, ge=0.0, le=1.0)
    cases: list[MemoryEquivalenceDatasetCase] = Field(default_factory=list)


class MemoryEquivalenceCaseResult(BaseModel):
    """Scored result for one benchmark case."""

    id: str
    coverage: float
    passed: bool


class MemoryEquivalenceReport(BaseModel):
    """Aggregate regression result over a memory-equivalence dataset."""

    dataset_id: str
    version: str
    average_coverage: float
    minimum_average_coverage: float
    passed: bool
    cases: list[MemoryEquivalenceCaseResult] = Field(default_factory=list)


def load_memory_equivalence_dataset(path: str | Path) -> MemoryEquivalenceDataset:
    """Load a benchmark dataset from disk."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return MemoryEquivalenceDataset.model_validate(payload)


def run_memory_equivalence_dataset(dataset: MemoryEquivalenceDataset) -> MemoryEquivalenceReport:
    """Score a memory-equivalence dataset against the current state-packet builder."""
    results: list[MemoryEquivalenceCaseResult] = []

    for case in dataset.cases:
        response = None
        if case.response_tool_calls:
            response = ChatResponse(
                content="",
                agent="tools",
                metadata={"tool_calls": case.response_tool_calls},
            )
        packet = build_session_state_packet(
            case.messages,
            conversation_summary=case.conversation_summary,
            response=response,
        )
        coverage = evaluate_state_packet_equivalence(
            EquivalenceCase(
                case_id=case.id,
                packet=packet,
                expected_fragments=tuple(case.expected_fragments),
            )
        )
        results.append(
            MemoryEquivalenceCaseResult(
                id=case.id,
                coverage=coverage,
                passed=coverage >= dataset.minimum_average_coverage,
            )
        )

    average = sum(result.coverage for result in results) / len(results) if results else 1.0

    return MemoryEquivalenceReport(
        dataset_id=dataset.dataset_id,
        version=dataset.version,
        average_coverage=average,
        minimum_average_coverage=dataset.minimum_average_coverage,
        passed=average >= dataset.minimum_average_coverage,
        cases=results,
    )

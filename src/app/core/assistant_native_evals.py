"""Deterministic replay evaluation for assistant-native continuity behavior."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from types import SimpleNamespace

from pydantic import BaseModel, Field

from src.app.core.conversation_actions import ContinuityResolution, resolve_conversation_continuity
from src.app.domain.models import MessageInput, PendingConversationAction

ASSISTANT_NATIVE_EVAL_DATASET_PATH = Path(
    "data/evaluation/datasets/assistant_native_continuity.v1.json"
)


class AssistantNativeEvalThresholds(BaseModel):
    """Release thresholds for deterministic assistant-native replays."""

    minimum_pass_rate: float = Field(ge=0.0, le=1.0)
    minimum_case_count: int = Field(ge=1)
    minimum_baseline_lift: float = Field(ge=0.0, le=1.0, default=0.0)


class AssistantNativeEvalCase(BaseModel):
    """One replay case for continuity resolution."""

    id: str
    description: str
    message_content: str
    pending_action: dict | None = None
    recent_actions: list[dict] = Field(default_factory=list)
    expected_resolution_type: str | None = None
    expected_forced_specialist: str | None = None
    expected_rewritten_content_contains: list[str] = Field(default_factory=list)
    expected_early_response_contains: list[str] = Field(default_factory=list)
    expected_clarification_requested: bool | None = None
    expected_matched_action_type: str | None = None


class AssistantNativeEvalDataset(BaseModel):
    """Versioned replay dataset."""

    dataset_id: str
    version: str
    description: str
    thresholds: AssistantNativeEvalThresholds
    cases: list[AssistantNativeEvalCase] = Field(default_factory=list)


class AssistantNativeEvalCaseResult(BaseModel):
    """Outcome for one replay case."""

    id: str
    description: str
    passed: bool
    baseline_passed: bool
    current_resolution_type: str | None = None
    baseline_resolution_type: str | None = None
    current_forced_specialist: str | None = None
    failures: list[str] = Field(default_factory=list)


class AssistantNativeEvalResult(BaseModel):
    """Summary for the replay suite."""

    dataset_id: str
    version: str
    generated_at: datetime
    case_count: int
    pass_count: int
    pass_rate: float
    baseline_pass_count: int
    baseline_pass_rate: float
    baseline_lift: float
    minimum_pass_rate_target: float
    minimum_baseline_lift_target: float
    minimum_case_count_target: int
    passing: bool
    failing_case_ids: list[str] = Field(default_factory=list)
    cases: list[AssistantNativeEvalCaseResult] = Field(default_factory=list)


@cache
def load_assistant_native_eval_dataset(
    path: Path | None = None,
) -> AssistantNativeEvalDataset:
    """Load the assistant-native replay dataset from disk."""
    dataset_path = path or ASSISTANT_NATIVE_EVAL_DATASET_PATH
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    return AssistantNativeEvalDataset.model_validate(payload)


def validate_assistant_native_eval_assets(
    *,
    path: Path | None = None,
) -> list[str]:
    """Validate replay assets and expectations."""
    dataset_path = path or ASSISTANT_NATIVE_EVAL_DATASET_PATH
    if not dataset_path.is_file():
        return [f"Missing assistant-native replay dataset: {dataset_path}"]

    try:
        dataset = load_assistant_native_eval_dataset(dataset_path)
    except Exception as exc:
        return [f"assistant-native replay dataset invalid: {exc}"]

    errors: list[str] = []
    if len(dataset.cases) < dataset.thresholds.minimum_case_count:
        errors.append("assistant-native replay dataset has fewer cases than the configured minimum")

    for case in dataset.cases:
        has_expectation = any(
            (
                case.expected_resolution_type,
                case.expected_forced_specialist,
                case.expected_rewritten_content_contains,
                case.expected_early_response_contains,
                case.expected_clarification_requested is not None,
                case.expected_matched_action_type,
            )
        )
        if not has_expectation:
            errors.append(f"{case.id}: replay case must define at least one expectation")

        if case.pending_action is not None:
            try:
                PendingConversationAction.model_validate(case.pending_action)
            except Exception as exc:
                errors.append(f"{case.id}: pending_action invalid: {exc}")

        for index, action_payload in enumerate(case.recent_actions):
            try:
                PendingConversationAction.model_validate(action_payload)
            except Exception as exc:
                errors.append(f"{case.id}: recent_actions[{index}] invalid: {exc}")

    return errors


def evaluate_assistant_native_replays(
    *,
    path: Path | None = None,
) -> AssistantNativeEvalResult:
    """Run the deterministic replay suite against the live continuity resolver."""
    dataset = load_assistant_native_eval_dataset(path)
    results: list[AssistantNativeEvalCaseResult] = []
    for case in dataset.cases:
        current = _run_case(case, resolver=_live_resolver)
        baseline = _run_case(case, resolver=_baseline_resolver)
        results.append(
            AssistantNativeEvalCaseResult(
                id=case.id,
                description=case.description,
                passed=current["passed"],
                baseline_passed=baseline["passed"],
                current_resolution_type=current["resolution_type"],
                baseline_resolution_type=baseline["resolution_type"],
                current_forced_specialist=current["forced_specialist"],
                failures=current["failures"],
            )
        )

    case_count = len(results)
    pass_count = sum(1 for result in results if result.passed)
    baseline_pass_count = sum(1 for result in results if result.baseline_passed)
    pass_rate = (pass_count / case_count) if case_count else 0.0
    baseline_pass_rate = (baseline_pass_count / case_count) if case_count else 0.0
    baseline_lift = pass_rate - baseline_pass_rate
    failing_case_ids = [result.id for result in results if not result.passed]
    thresholds = dataset.thresholds

    passing = (
        case_count >= thresholds.minimum_case_count
        and pass_rate >= thresholds.minimum_pass_rate
        and baseline_lift >= thresholds.minimum_baseline_lift
    )

    return AssistantNativeEvalResult(
        dataset_id=dataset.dataset_id,
        version=dataset.version,
        generated_at=datetime.now(UTC),
        case_count=case_count,
        pass_count=pass_count,
        pass_rate=pass_rate,
        baseline_pass_count=baseline_pass_count,
        baseline_pass_rate=baseline_pass_rate,
        baseline_lift=baseline_lift,
        minimum_pass_rate_target=thresholds.minimum_pass_rate,
        minimum_baseline_lift_target=thresholds.minimum_baseline_lift,
        minimum_case_count_target=thresholds.minimum_case_count,
        passing=passing,
        failing_case_ids=failing_case_ids,
        cases=results,
    )


def _run_case(
    case: AssistantNativeEvalCase,
    *,
    resolver,
) -> dict[str, object]:
    message = MessageInput(
        content=case.message_content,
        source="eval",
        user_id="assistant-native-eval",
    )
    pending_action = (
        PendingConversationAction.model_validate(case.pending_action)
        if isinstance(case.pending_action, dict)
        else None
    )
    recent_artifacts = [
        SimpleNamespace(
            artifact_type="conversation_action",
            payload=PendingConversationAction.model_validate(action).model_dump(mode="json"),
        )
        for action in case.recent_actions
    ]
    resolution = resolver(
        message,
        pending_action=pending_action,
        recent_artifacts=recent_artifacts,
    )
    failures = _validate_resolution(case, resolution)
    return {
        "passed": len(failures) == 0,
        "failures": failures,
        "resolution_type": _resolution_type(resolution),
        "forced_specialist": _forced_specialist(resolution),
    }


def _validate_resolution(
    case: AssistantNativeEvalCase,
    resolution: ContinuityResolution,
) -> list[str]:
    failures: list[str] = []
    resolution_type = _resolution_type(resolution)
    if case.expected_resolution_type != resolution_type:
        failures.append(
            f"expected resolution type {case.expected_resolution_type!r}, got {resolution_type!r}"
        )

    forced_specialist = _forced_specialist(resolution)
    if case.expected_forced_specialist != forced_specialist:
        failures.append(
            f"expected forced specialist {case.expected_forced_specialist!r}, "
            f"got {forced_specialist!r}"
        )

    rewritten_content = resolution.message.content
    for expected in case.expected_rewritten_content_contains:
        if expected.casefold() not in rewritten_content.casefold():
            failures.append(f"rewritten content missing {expected!r}")

    early_response_content = resolution.early_response.content if resolution.early_response else ""
    for expected in case.expected_early_response_contains:
        if expected.casefold() not in early_response_content.casefold():
            failures.append(f"early response missing {expected!r}")

    clarification_requested = _clarification_requested(resolution)
    if (
        case.expected_clarification_requested is not None
        and clarification_requested != case.expected_clarification_requested
    ):
        failures.append(
            "expected clarification_requested="
            f"{case.expected_clarification_requested}, got {clarification_requested}"
        )

    matched_action_type = (
        resolution.matched_action.action_type if resolution.matched_action else None
    )
    if case.expected_matched_action_type != matched_action_type:
        failures.append(
            f"expected matched action type {case.expected_matched_action_type!r}, "
            f"got {matched_action_type!r}"
        )

    return failures


def _live_resolver(
    message: MessageInput,
    *,
    pending_action: PendingConversationAction | None,
    recent_artifacts: list[object],
) -> ContinuityResolution:
    return resolve_conversation_continuity(
        message,
        pending_action=pending_action,
        recent_artifacts=recent_artifacts,
    )


def _baseline_resolver(
    message: MessageInput,
    *,
    pending_action: PendingConversationAction | None,
    recent_artifacts: list[object],
) -> ContinuityResolution:
    del pending_action, recent_artifacts
    return ContinuityResolution(message=message)


def _resolution_type(resolution: ContinuityResolution) -> str | None:
    metadata = resolution.message.metadata
    if resolution.early_response is not None and isinstance(
        resolution.early_response.metadata, dict
    ):
        metadata = resolution.early_response.metadata

    continuity = metadata.get("continuity_resolution") if isinstance(metadata, dict) else None
    if isinstance(continuity, dict) and isinstance(continuity.get("type"), str):
        return str(continuity["type"])
    return None


def _forced_specialist(resolution: ContinuityResolution) -> str | None:
    if resolution.forced_intent is None:
        return None
    specialist = getattr(resolution.forced_intent, "specialist", None)
    if specialist is None:
        return None
    return str(specialist)


def _clarification_requested(resolution: ContinuityResolution) -> bool:
    metadata = resolution.message.metadata
    if resolution.early_response is not None and isinstance(
        resolution.early_response.metadata, dict
    ):
        metadata = resolution.early_response.metadata
    return bool(isinstance(metadata, dict) and metadata.get("clarification_requested"))

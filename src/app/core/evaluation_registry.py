"""Structured evaluation asset registry for specialist runtimes."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from src.app.config import Settings
from src.app.domain.models import Specialist
from src.app.domain.runtime import AgentRuntimeConfig, get_agent_runtime_config

EVALUATION_ROOT = Path("data/evaluation")
RUBRICS_DIR = EVALUATION_ROOT / "rubrics"
DATASETS_DIR = EVALUATION_ROOT / "datasets"

SPECIALIST_ORDER: tuple[Specialist, ...] = (
    Specialist.DIARY,
    Specialist.MEMORY,
    Specialist.RESEARCH,
    Specialist.REVIEW,
    Specialist.NOTIFICATION,
    Specialist.TOOLS,
    Specialist.SAVE,
    Specialist.PROJECT,
    Specialist.COMMUNICATIONS,
    Specialist.PLAN_DAY,
    Specialist.SOCRATIC,
)

_RUBRIC_FILES: dict[Specialist, str] = {
    Specialist.DIARY: "diary.md",
    Specialist.MEMORY: "memory.md",
    Specialist.RESEARCH: "research.md",
    Specialist.REVIEW: "review.md",
    Specialist.NOTIFICATION: "notification.md",
    Specialist.TOOLS: "tools.md",
    Specialist.SAVE: "save.md",
    Specialist.PROJECT: "project.md",
    Specialist.COMMUNICATIONS: "communications.md",
    Specialist.PLAN_DAY: "plan_day.md",
    Specialist.SOCRATIC: "socratic.md",
}

_DATASET_FILES: dict[Specialist, str] = {
    specialist: f"{specialist.value}.v1.json" for specialist in SPECIALIST_ORDER
}


class EvalThresholds(BaseModel):
    """Quality gates for a specialist evaluation suite."""

    minimum_pass_rate: float = Field(ge=0.0, le=1.0)
    minimum_average_score: float = Field(ge=0.0, le=1.0)
    max_regression: float = Field(ge=0.0, le=1.0)


class EvalCase(BaseModel):
    """One golden evaluation example."""

    id: str
    prompt: str
    expected_behaviors: list[str] = Field(default_factory=list)
    disallowed_behaviors: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)


class EvalDataset(BaseModel):
    """Versioned specialist dataset."""

    dataset_id: str
    specialist: Specialist
    version: str
    rubric_id: str
    description: str
    thresholds: EvalThresholds
    cases: list[EvalCase] = Field(default_factory=list)


class EvalRubricAsset(BaseModel):
    """Metadata about a specialist rubric asset."""

    rubric_id: str
    specialist: Specialist
    version: str
    universal_rubric: str = "universal.md"
    path: str


class EvalSuite(BaseModel):
    """Joined runtime/evaluation contract for a specialist."""

    specialist: Specialist
    runtime: AgentRuntimeConfig
    rubric: EvalRubricAsset
    dataset: EvalDataset


def universal_rubric_path() -> Path:
    """Return the universal rubric path."""
    return RUBRICS_DIR / "universal.md"


def rubric_path_for_specialist(specialist: Specialist) -> Path:
    """Return the rubric path for a specialist."""
    return RUBRICS_DIR / _RUBRIC_FILES[specialist]


def dataset_path_for_specialist(specialist: Specialist) -> Path:
    """Return the dataset path for a specialist."""
    return DATASETS_DIR / _DATASET_FILES[specialist]


@cache
def load_eval_dataset(specialist: Specialist | str) -> EvalDataset:
    """Load a specialist dataset from disk."""
    resolved = Specialist(specialist)
    path = dataset_path_for_specialist(resolved)
    payload = json.loads(path.read_text(encoding="utf-8"))
    dataset = EvalDataset.model_validate(payload)
    if dataset.specialist != resolved:
        msg = (
            f"Dataset mismatch for {resolved.value}: "
            f"expected {resolved.value}, found {dataset.specialist.value}"
        )
        raise ValueError(msg)
    return dataset


@cache
def load_eval_rubric_asset(specialist: Specialist | str, rubric_id: str) -> EvalRubricAsset:
    """Resolve rubric metadata for a specialist."""
    resolved = Specialist(specialist)
    path = rubric_path_for_specialist(resolved)
    if not path.is_file():
        msg = f"Rubric file missing for {resolved.value}: {path}"
        raise FileNotFoundError(msg)
    return EvalRubricAsset(
        rubric_id=rubric_id,
        specialist=resolved,
        version="v1",
        path=path.as_posix(),
    )


def load_eval_suite(
    specialist: Specialist | str,
    *,
    settings: Settings | None = None,
) -> EvalSuite:
    """Join runtime metadata, rubric metadata, and dataset metadata."""
    resolved = Specialist(specialist)
    runtime_settings = settings
    if runtime_settings is None:
        from src.app.config import get_settings

        runtime_settings = get_settings()

    runtime = get_agent_runtime_config(resolved, settings=runtime_settings)
    dataset = load_eval_dataset(resolved)
    rubric = load_eval_rubric_asset(resolved, runtime.eval_rubric_id)

    if dataset.rubric_id != runtime.eval_rubric_id:
        msg = (
            f"Evaluation contract drift for {resolved.value}: "
            f"runtime rubric={runtime.eval_rubric_id}, dataset rubric={dataset.rubric_id}"
        )
        raise ValueError(msg)

    return EvalSuite(
        specialist=resolved,
        runtime=runtime,
        rubric=rubric,
        dataset=dataset,
    )


def list_eval_suites(*, settings: Settings | None = None) -> list[EvalSuite]:
    """Load all specialist evaluation suites."""
    return [load_eval_suite(specialist, settings=settings) for specialist in SPECIALIST_ORDER]


def validate_evaluation_assets(*, settings: Settings | None = None) -> list[str]:
    """Validate that all rubrics/datasets exist and align with runtime contracts."""
    errors: list[str] = []

    if not RUBRICS_DIR.is_dir():
        errors.append(f"Missing rubrics directory: {RUBRICS_DIR}")
    if not DATASETS_DIR.is_dir():
        errors.append(f"Missing datasets directory: {DATASETS_DIR}")
    if not universal_rubric_path().is_file():
        errors.append(f"Missing universal rubric: {universal_rubric_path()}")

    for specialist in SPECIALIST_ORDER:
        rubric_path = rubric_path_for_specialist(specialist)
        dataset_path = dataset_path_for_specialist(specialist)

        if not rubric_path.is_file():
            errors.append(f"Missing rubric for {specialist.value}: {rubric_path}")
            continue
        if not dataset_path.is_file():
            errors.append(f"Missing dataset for {specialist.value}: {dataset_path}")
            continue

        try:
            suite = load_eval_suite(specialist, settings=settings)
        except Exception as exc:
            errors.append(f"{specialist.value}: {exc}")
            continue

        if not suite.dataset.cases:
            errors.append(f"{specialist.value}: dataset must contain at least one case")

    return errors

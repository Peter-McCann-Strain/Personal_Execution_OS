"""Tests for structured evaluation suites and golden datasets."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.app.core.evaluation_registry import (
    SPECIALIST_ORDER,
    EvalDataset,
    EvalRubricAsset,
    EvalThresholds,
    list_eval_suites,
    load_eval_suite,
    validate_evaluation_assets,
)
from src.app.domain.models import Specialist
from src.app.domain.runtime import AgentRuntimeConfig


@pytest.fixture(autouse=True)
def _clear_eval_registry_caches():
    from src.app.core import evaluation_registry as registry

    registry.load_eval_dataset.cache_clear()
    registry.load_eval_rubric_asset.cache_clear()
    yield
    registry.load_eval_dataset.cache_clear()
    registry.load_eval_rubric_asset.cache_clear()


def test_all_specialists_have_eval_suites():
    suites = list_eval_suites()
    assert [suite.specialist for suite in suites] == list(SPECIALIST_ORDER)


def test_eval_assets_validate_cleanly():
    assert validate_evaluation_assets() == []


def test_each_suite_has_cases_and_matching_rubric():
    for specialist in SPECIALIST_ORDER:
        suite = load_eval_suite(specialist)
        assert suite.dataset.cases
        assert suite.dataset.rubric_id == suite.runtime.eval_rubric_id
        assert suite.rubric.path.endswith(".md")


def test_load_eval_dataset_detects_specialist_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from src.app.core import evaluation_registry as registry

    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(
        json.dumps(
            {
                "dataset_id": "memory.v1",
                "specialist": "memory",
                "version": "v1",
                "rubric_id": "memory.v1",
                "description": "Mismatch test",
                "thresholds": {
                    "minimum_pass_rate": 0.8,
                    "minimum_average_score": 0.8,
                    "max_regression": 0.1,
                },
                "cases": [{"id": "c1", "prompt": "Remember this"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(registry, "dataset_path_for_specialist", lambda _specialist: dataset_path)

    with pytest.raises(ValueError, match="Dataset mismatch"):
        registry.load_eval_dataset(Specialist.DIARY)


def test_load_eval_rubric_asset_requires_file(monkeypatch: pytest.MonkeyPatch):
    from src.app.core import evaluation_registry as registry

    monkeypatch.setattr(
        registry,
        "rubric_path_for_specialist",
        lambda _specialist: Path("/definitely/missing-rubric.md"),
    )

    with pytest.raises(FileNotFoundError, match="Rubric file missing"):
        registry.load_eval_rubric_asset(Specialist.DIARY, "diary.v1")


def test_load_eval_suite_propagates_when_get_settings_fails(monkeypatch: pytest.MonkeyPatch):
    from src.app.core import evaluation_registry as registry

    def _raise_settings():
        raise RuntimeError("boom")

    monkeypatch.setattr("src.app.config.get_settings", _raise_settings)

    with pytest.raises(RuntimeError, match="boom"):
        registry.load_eval_suite(Specialist.DIARY)


def test_load_eval_suite_detects_contract_drift(monkeypatch: pytest.MonkeyPatch):
    from src.app.core import evaluation_registry as registry

    monkeypatch.setattr(
        registry,
        "get_agent_runtime_config",
        lambda specialist, *, settings: AgentRuntimeConfig(
            specialist=specialist,
            prompt_source="src/app/agents/prompts/diary.py",
            allowed_tools=[],
            confirmation_policy="never",
            memory_namespace="session.diary",
            model_policy="test-model",
            eval_rubric_id="diary.v1",
            max_token_budget=1024,
            output_schema="chat_response",
        ),
    )
    monkeypatch.setattr(
        registry,
        "load_eval_dataset",
        lambda specialist: EvalDataset(
            dataset_id="diary.v1",
            specialist=Specialist.DIARY,
            version="v1",
            rubric_id="diary.v2",
            description="Diary dataset",
            thresholds=EvalThresholds(
                minimum_pass_rate=0.8,
                minimum_average_score=0.8,
                max_regression=0.1,
            ),
            cases=[{"id": "case-1", "prompt": "Log my day"}],
        ),
    )
    monkeypatch.setattr(
        registry,
        "load_eval_rubric_asset",
        lambda specialist, rubric_id: EvalRubricAsset(
            rubric_id=rubric_id,
            specialist=Specialist.DIARY,
            version="v1",
            path="data/evaluation/rubrics/diary.md",
        ),
    )

    with pytest.raises(ValueError, match="Evaluation contract drift"):
        registry.load_eval_suite(Specialist.DIARY, settings=MagicMock())


def test_validate_evaluation_assets_reports_missing_roots(monkeypatch: pytest.MonkeyPatch):
    from src.app.core import evaluation_registry as registry

    monkeypatch.setattr(registry, "RUBRICS_DIR", Path("/missing/rubrics"))
    monkeypatch.setattr(registry, "DATASETS_DIR", Path("/missing/datasets"))
    monkeypatch.setattr(registry, "universal_rubric_path", lambda: Path("/missing/universal.md"))
    monkeypatch.setattr(registry, "SPECIALIST_ORDER", ())

    errors = registry.validate_evaluation_assets()

    assert "Missing rubrics directory: /missing/rubrics" in errors
    assert "Missing datasets directory: /missing/datasets" in errors
    assert "Missing universal rubric: /missing/universal.md" in errors


def test_validate_evaluation_assets_reports_missing_specialist_files(
    monkeypatch: pytest.MonkeyPatch,
):
    from src.app.core import evaluation_registry as registry

    rubric_path = Path("/missing/diary.md")
    dataset_path = Path("/missing/diary.v1.json")
    monkeypatch.setattr(registry, "SPECIALIST_ORDER", (Specialist.DIARY,))
    monkeypatch.setattr(registry, "rubric_path_for_specialist", lambda specialist: rubric_path)
    monkeypatch.setattr(registry, "dataset_path_for_specialist", lambda specialist: dataset_path)
    monkeypatch.setattr(registry, "RUBRICS_DIR", Path("."))
    monkeypatch.setattr(registry, "DATASETS_DIR", Path("."))
    monkeypatch.setattr(registry, "universal_rubric_path", lambda: Path(__file__))

    errors = registry.validate_evaluation_assets()

    assert errors == [f"Missing rubric for diary: {rubric_path}"]


def test_validate_evaluation_assets_reports_missing_dataset_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from src.app.core import evaluation_registry as registry

    rubric_path = tmp_path / "diary.md"
    dataset_path = tmp_path / "diary.v1.json"
    rubric_path.write_text("rubric", encoding="utf-8")
    monkeypatch.setattr(registry, "SPECIALIST_ORDER", (Specialist.DIARY,))
    monkeypatch.setattr(registry, "rubric_path_for_specialist", lambda specialist: rubric_path)
    monkeypatch.setattr(registry, "dataset_path_for_specialist", lambda specialist: dataset_path)
    monkeypatch.setattr(registry, "RUBRICS_DIR", tmp_path)
    monkeypatch.setattr(registry, "DATASETS_DIR", tmp_path)
    monkeypatch.setattr(registry, "universal_rubric_path", lambda: Path(__file__))

    errors = registry.validate_evaluation_assets()

    assert errors == [f"Missing dataset for diary: {dataset_path}"]


def test_validate_evaluation_assets_reports_load_errors_and_empty_cases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from src.app.core import evaluation_registry as registry

    rubric_path = tmp_path / "diary.md"
    dataset_path = tmp_path / "diary.v1.json"
    rubric_path.write_text("rubric", encoding="utf-8")
    dataset_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(registry, "SPECIALIST_ORDER", (Specialist.DIARY,))
    monkeypatch.setattr(registry, "rubric_path_for_specialist", lambda specialist: rubric_path)
    monkeypatch.setattr(registry, "dataset_path_for_specialist", lambda specialist: dataset_path)
    monkeypatch.setattr(registry, "RUBRICS_DIR", tmp_path)
    monkeypatch.setattr(registry, "DATASETS_DIR", tmp_path)
    monkeypatch.setattr(registry, "universal_rubric_path", lambda: rubric_path)
    monkeypatch.setattr(
        registry,
        "load_eval_suite",
        lambda specialist, settings=None: (_ for _ in ()).throw(RuntimeError("bad suite")),
    )

    errors = registry.validate_evaluation_assets()

    assert errors == ["diary: bad suite"]

    monkeypatch.setattr(
        registry,
        "load_eval_suite",
        lambda specialist, settings=None: MagicMock(dataset=MagicMock(cases=[])),
    )

    errors = registry.validate_evaluation_assets()

    assert errors == ["diary: dataset must contain at least one case"]

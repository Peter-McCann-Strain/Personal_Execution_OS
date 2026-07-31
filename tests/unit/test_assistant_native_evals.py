"""Tests for deterministic assistant-native replay evaluation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.app.core import assistant_native_evals as replay_module


@pytest.fixture(autouse=True)
def _clear_replay_cache():
    replay_module.load_assistant_native_eval_dataset.cache_clear()
    yield
    replay_module.load_assistant_native_eval_dataset.cache_clear()


def test_validate_assistant_native_eval_assets_clean():
    assert replay_module.validate_assistant_native_eval_assets() == []


def test_evaluate_assistant_native_replays_passes_and_beats_baseline():
    result = replay_module.evaluate_assistant_native_replays()

    assert result.passing is True
    assert result.pass_rate == 1.0
    assert result.case_count >= 6
    assert result.baseline_pass_rate < result.pass_rate
    assert result.baseline_lift >= result.minimum_baseline_lift_target
    assert result.failing_case_ids == []


def test_validate_assistant_native_eval_assets_reports_missing_expectations(
    tmp_path: Path,
):
    dataset_path = tmp_path / "assistant-native.json"
    dataset_path.write_text(
        json.dumps(
            {
                "dataset_id": "assistant_native_continuity.v1",
                "version": "v1",
                "description": "Invalid dataset",
                "thresholds": {
                    "minimum_pass_rate": 1.0,
                    "minimum_case_count": 1,
                    "minimum_baseline_lift": 0.0,
                },
                "cases": [
                    {
                        "id": "case-1",
                        "description": "No expectations",
                        "message_content": "try again",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    errors = replay_module.validate_assistant_native_eval_assets(path=dataset_path)

    assert errors == ["case-1: replay case must define at least one expectation"]


def test_evaluate_assistant_native_replays_reports_failing_case(
    tmp_path: Path,
):
    dataset_path = tmp_path / "assistant-native.json"
    dataset_path.write_text(
        json.dumps(
            {
                "dataset_id": "assistant_native_continuity.v1",
                "version": "v1",
                "description": "One failing case",
                "thresholds": {
                    "minimum_pass_rate": 1.0,
                    "minimum_case_count": 1,
                    "minimum_baseline_lift": 0.0,
                },
                "cases": [
                    {
                        "id": "case-1",
                        "description": "Impossible expectation",
                        "message_content": "try again",
                        "expected_resolution_type": "retry_pending_action",
                        "expected_forced_specialist": "save",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = replay_module.evaluate_assistant_native_replays(path=dataset_path)

    assert result.passing is False
    assert result.failing_case_ids == ["case-1"]
    assert result.cases[0].failures

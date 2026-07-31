"""Tests for deterministic memory-equivalence checks."""

from __future__ import annotations

import json
from pathlib import Path

from src.app.core.memory_equivalence import (
    load_memory_equivalence_dataset,
    run_memory_equivalence_dataset,
)


def test_load_memory_equivalence_dataset(tmp_path: Path):
    """Dataset files should load into the structured benchmark model."""
    dataset_path = tmp_path / "memory_equivalence.json"
    dataset_path.write_text(
        json.dumps(
            {
                "dataset_id": "memory-equivalence",
                "version": "v1",
                "minimum_average_coverage": 0.9,
                "cases": [
                    {
                        "id": "case-1",
                        "messages": [{"role": "user", "content": "I prefer concise answers."}],
                        "expected_fragments": ["concise answers"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    dataset = load_memory_equivalence_dataset(dataset_path)

    assert dataset.dataset_id == "memory-equivalence"
    assert dataset.cases[0].id == "case-1"


def test_run_memory_equivalence_dataset_passes_for_preserved_fragments():
    """The benchmark should pass when expected fragments survive in the packet."""
    dataset = load_memory_equivalence_dataset("data/evaluation/datasets/memory_equivalence.v1.json")

    report = run_memory_equivalence_dataset(dataset)

    assert report.passed is True
    assert report.average_coverage >= dataset.minimum_average_coverage
    assert all(case.coverage >= 0.95 for case in report.cases)

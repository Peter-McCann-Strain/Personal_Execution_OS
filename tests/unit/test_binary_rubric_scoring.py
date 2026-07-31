"""Tests that the binary rubric scoring math matches the expected sum-of-Ys."""

from __future__ import annotations

import pytest

from src.app.core.auto_judge import (
    AutoJudgeScores,
    summarize_specialist_dimensions,
)
from src.app.core.rubric_loader import (
    BinaryCheck,
    RubricDimension,
    SpecialistRubric,
    load_specialist_rubric,
)
from src.app.domain.models import Specialist


def _make_rubric(specialist: Specialist, check_counts: list[int]) -> SpecialistRubric:
    """Build an in-memory rubric with the given per-dimension check counts."""
    dimensions: list[RubricDimension] = []
    for idx, count in enumerate(check_counts):
        name = f"Dim {idx + 1}"
        key = f"dim_{idx + 1}"
        checks = [BinaryCheck(id=f"Q{j + 1}", question=f"Sub-check {j + 1}?") for j in range(count)]
        dimensions.append(RubricDimension(name=name, key=key, checks=checks))
    return SpecialistRubric(
        specialist=specialist,
        version="v2",
        path=f"virtual/{specialist.value}.md",
        dimensions=dimensions,
    )


class TestDimensionScoringMath:
    def test_all_true_returns_count(self) -> None:
        dim = RubricDimension(
            name="Example",
            key="example",
            checks=[
                BinaryCheck(id="Q1", question="A?"),
                BinaryCheck(id="Q2", question="B?"),
                BinaryCheck(id="Q3", question="C?"),
                BinaryCheck(id="Q4", question="D?"),
            ],
        )
        assert dim.score({"Q1": True, "Q2": True, "Q3": True, "Q4": True}) == 4
        assert dim.normalized_score({"Q1": True, "Q2": True, "Q3": True, "Q4": True}) == 1.0

    def test_all_false_returns_zero(self) -> None:
        dim = RubricDimension(
            name="Example",
            key="example",
            checks=[
                BinaryCheck(id="Q1", question="A?"),
                BinaryCheck(id="Q2", question="B?"),
                BinaryCheck(id="Q3", question="C?"),
            ],
        )
        assert dim.score({"Q1": False, "Q2": False, "Q3": False}) == 0
        assert dim.normalized_score({"Q1": False, "Q2": False, "Q3": False}) == 0.0

    def test_partial_true_sums_correctly(self) -> None:
        dim = RubricDimension(
            name="Example",
            key="example",
            checks=[
                BinaryCheck(id="Q1", question="A?"),
                BinaryCheck(id="Q2", question="B?"),
                BinaryCheck(id="Q3", question="C?"),
                BinaryCheck(id="Q4", question="D?"),
            ],
        )
        answers = {"Q1": True, "Q2": False, "Q3": True, "Q4": True}
        assert dim.score(answers) == 3
        assert dim.normalized_score(answers) == 0.75

    def test_missing_answers_count_as_false(self) -> None:
        dim = RubricDimension(
            name="Example",
            key="example",
            checks=[
                BinaryCheck(id="Q1", question="A?"),
                BinaryCheck(id="Q2", question="B?"),
                BinaryCheck(id="Q3", question="C?"),
            ],
        )
        assert dim.score({"Q1": True}) == 1
        assert dim.score({}) == 0

    def test_answer_keys_are_case_insensitive(self) -> None:
        dim = RubricDimension(
            name="Example",
            key="example",
            checks=[
                BinaryCheck(id="Q1", question="A?"),
                BinaryCheck(id="Q2", question="B?"),
                BinaryCheck(id="Q3", question="C?"),
            ],
        )
        assert dim.score({"q1": True, "q2": True, "q3": False}) == 2


class TestRubricWhole:
    def test_score_dimensions_returns_all_dimensions(self) -> None:
        rubric = _make_rubric(Specialist.DIARY, [3, 4])
        answers = {
            "dim_1": {"Q1": True, "Q2": False, "Q3": True},
            "dim_2": {"Q1": True, "Q2": True, "Q3": True, "Q4": False},
        }
        result = rubric.score_dimensions(answers)
        assert result == {"dim_1": 2, "dim_2": 3}


class TestSummarizeSpecialistDimensions:
    def test_summary_matches_expected_shape(self) -> None:
        rubric = _make_rubric(Specialist.DIARY, [3])
        scores = AutoJudgeScores(
            relevance=0.8,
            actionability=0.8,
            tone=0.8,
            conciseness=0.8,
            reasoning="ok",
            specialist_checks={"dim_1": {"Q1": True, "Q2": False, "Q3": True}},
        )
        summary = summarize_specialist_dimensions(rubric, scores)
        assert set(summary.keys()) == {"dim_1"}
        entry = summary["dim_1"]
        assert entry["name"] == "Dim 1"
        assert entry["score"] == 2
        assert entry["max"] == 3
        assert entry["normalized"] == pytest.approx(0.667, abs=1e-3)
        assert entry["checks"] == {"Q1": True, "Q2": False, "Q3": True}

    def test_missing_checks_default_to_false(self) -> None:
        rubric = _make_rubric(Specialist.DIARY, [4])
        scores = AutoJudgeScores(
            relevance=0.8,
            actionability=0.8,
            tone=0.8,
            conciseness=0.8,
            reasoning="ok",
            specialist_checks={"dim_1": {"Q1": True}},
        )
        summary = summarize_specialist_dimensions(rubric, scores)
        entry = summary["dim_1"]
        assert entry["score"] == 1
        assert entry["checks"] == {"Q1": True, "Q2": False, "Q3": False, "Q4": False}

    def test_works_with_real_diary_rubric(self) -> None:
        rubric = load_specialist_rubric(Specialist.DIARY)
        # Build a set of all-True answers across every real dimension.
        scores = AutoJudgeScores(
            relevance=0.9,
            actionability=0.9,
            tone=0.9,
            conciseness=0.9,
            reasoning="all true",
            specialist_checks={
                dim.key: {check.id: True for check in dim.checks} for dim in rubric.dimensions
            },
        )
        summary = summarize_specialist_dimensions(rubric, scores)
        for dim in rubric.dimensions:
            assert summary[dim.key]["score"] == dim.max_score
            assert summary[dim.key]["normalized"] == 1.0


class TestAutoJudgeScoresModel:
    def test_defaults_to_empty_specialist_checks(self) -> None:
        scores = AutoJudgeScores(
            relevance=0.8,
            actionability=0.8,
            tone=0.8,
            conciseness=0.8,
            reasoning="ok",
        )
        assert scores.specialist_checks == {}

    def test_accepts_nested_boolean_checks(self) -> None:
        scores = AutoJudgeScores(
            relevance=0.8,
            actionability=0.8,
            tone=0.8,
            conciseness=0.8,
            reasoning="ok",
            specialist_checks={"grounding": {"Q1": True, "Q2": False}},
        )
        assert scores.specialist_checks["grounding"]["Q1"] is True
        assert scores.specialist_checks["grounding"]["Q2"] is False

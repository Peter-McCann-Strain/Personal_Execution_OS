"""Tests for the binary-check rubric loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.app.core.rubric_loader import (
    BinaryCheck,
    RubricDimension,
    SpecialistRubric,
    load_all_specialist_rubrics,
    load_specialist_rubric,
    parse_rubric_markdown,
    rubric_prompt_snippet,
)
from src.app.domain.models import Specialist

_RUBRIC_SPECIALISTS: tuple[Specialist, ...] = (
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


@pytest.fixture(autouse=True)
def _clear_loader_cache() -> None:
    load_specialist_rubric.cache_clear()
    yield
    load_specialist_rubric.cache_clear()


class TestLoadsRealRubrics:
    """Every shipped agent rubric must parse into at least one binary dimension."""

    def test_loads_all_agent_rubrics(self) -> None:
        rubrics = load_all_specialist_rubrics()
        specialists_loaded = set(rubrics)
        for specialist in _RUBRIC_SPECIALISTS:
            assert specialist in specialists_loaded, f"Rubric for {specialist.value} did not load"

    @pytest.mark.parametrize("specialist", list(_RUBRIC_SPECIALISTS))
    def test_each_rubric_has_binary_dimensions(self, specialist: Specialist) -> None:
        rubric = load_specialist_rubric(specialist)
        assert isinstance(rubric, SpecialistRubric)
        assert rubric.dimensions, f"{specialist.value} rubric has no dimensions"
        for dim in rubric.dimensions:
            assert 3 <= len(dim.checks) <= 5, (
                f"{specialist.value}.{dim.key}: {len(dim.checks)} checks, expected 3-5"
            )
            for check in dim.checks:
                assert check.id.startswith("Q"), f"Unexpected check id {check.id}"
                assert check.question.endswith("?"), (
                    f"{specialist.value}.{dim.key}.{check.id}: question must end with '?'"
                )

    def test_slug_keys_are_stable(self) -> None:
        diary = load_specialist_rubric(Specialist.DIARY)
        keys = [dim.key for dim in diary.dimensions]
        # Expected dimensions: Emotional Attunement + Reflection Depth
        assert "emotional_attunement" in keys
        assert "reflection_depth" in keys

    def test_research_has_source_quality_and_synthesis_depth(self) -> None:
        research = load_specialist_rubric(Specialist.RESEARCH)
        keys = {dim.key for dim in research.dimensions}
        assert "source_quality" in keys
        assert "synthesis_depth" in keys

    def test_tools_includes_execution_and_policy(self) -> None:
        tools = load_specialist_rubric(Specialist.TOOLS)
        keys = {dim.key for dim in tools.dimensions}
        assert "execution_correctness" in keys
        assert "policy_compliance" in keys


class TestParseRubricMarkdown:
    def test_parses_minimum_dimension(self) -> None:
        markdown = (
            "# Demo Rubric v3\n\n"
            "This extends [universal.md](universal.md).\n\n"
            "## Binary Scoring\n\nBlurb.\n\n"
            "## Specialist Dimension 1: Example Dim\n\n"
            "- Q1: Does it do the thing? Y/N\n"
            "- Q2: Is it concise enough? Y/N\n"
            "- Q3: Is it decisive? Y/N\n"
        )
        rubric = parse_rubric_markdown(
            markdown,
            specialist=Specialist.DIARY,
            path="virtual/demo.md",
        )
        assert rubric.version == "v3"
        assert len(rubric.dimensions) == 1
        dim = rubric.dimensions[0]
        assert dim.name == "Example Dim"
        assert dim.key == "example_dim"
        assert len(dim.checks) == 3
        assert dim.checks[0].id == "Q1"
        assert dim.checks[0].question.endswith("?")

    def test_rejects_dimension_with_fewer_than_three_checks(self) -> None:
        markdown = (
            "# Broken Rubric v1\n\n"
            "## Specialist Dimension 1: Bad Dim\n\n"
            "- Q1: Only one check? Y/N\n"
        )
        with pytest.raises(ValueError, match="must have 3-5 binary sub-checks"):
            parse_rubric_markdown(
                markdown,
                specialist=Specialist.DIARY,
                path="virtual/broken.md",
            )

    def test_rejects_dimension_with_no_checks(self) -> None:
        markdown = (
            "# Broken Rubric v1\n\n"
            "## Specialist Dimension 1: Empty Dim\n\n"
            "Some narrative text but no list items.\n"
        )
        with pytest.raises(ValueError, match="no binary sub-checks"):
            parse_rubric_markdown(
                markdown,
                specialist=Specialist.DIARY,
                path="virtual/empty.md",
            )

    def test_rejects_rubric_with_no_dimensions(self) -> None:
        markdown = "# Empty Rubric v1\n\n## Binary Scoring\n\nNo dimensions.\n"
        with pytest.raises(ValueError, match="no Specialist Dimension sections"):
            parse_rubric_markdown(
                markdown,
                specialist=Specialist.DIARY,
                path="virtual/nodim.md",
            )

    def test_handles_parenthesised_yn_suffix(self) -> None:
        markdown = (
            "# Demo Rubric v1\n\n"
            "## Specialist Dimension 1: Dim\n\n"
            "- Q1: Is format tolerated (Y/N)\n"
            "- Q2: And this one too (Y/N)\n"
            "- Q3: And this one Y/N\n"
        )
        rubric = parse_rubric_markdown(
            markdown,
            specialist=Specialist.MEMORY,
            path="virtual/paren.md",
        )
        assert [c.id for c in rubric.dimensions[0].checks] == ["Q1", "Q2", "Q3"]


class TestRubricPromptSnippet:
    def test_prompt_snippet_includes_all_checks(self) -> None:
        rubric = load_specialist_rubric(Specialist.DIARY)
        snippet = rubric_prompt_snippet(rubric)
        for dim in rubric.dimensions:
            assert dim.name in snippet
            assert f"key: {dim.key}" in snippet
            for check in dim.checks:
                assert check.id in snippet


class TestMissingRubric:
    def test_missing_file_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.app.core import evaluation_registry, rubric_loader

        missing_path = tmp_path / "missing.md"
        monkeypatch.setattr(
            evaluation_registry,
            "rubric_path_for_specialist",
            lambda _spec: missing_path,
        )
        monkeypatch.setattr(
            rubric_loader,
            "rubric_path_for_specialist",
            lambda _spec: missing_path,
        )
        load_specialist_rubric.cache_clear()
        with pytest.raises(FileNotFoundError):
            load_specialist_rubric(Specialist.DIARY)


class TestDimensionDataclass:
    def test_binary_check_question_roundtrip(self) -> None:
        check = BinaryCheck(id="Q1", question="Does it land?")
        assert check.id == "Q1"
        assert check.question == "Does it land?"

    def test_rubric_dimension_max_score(self) -> None:
        dim = RubricDimension(
            name="Thing",
            key="thing",
            checks=[
                BinaryCheck(id="Q1", question="A?"),
                BinaryCheck(id="Q2", question="B?"),
                BinaryCheck(id="Q3", question="C?"),
            ],
        )
        assert dim.max_score == 3

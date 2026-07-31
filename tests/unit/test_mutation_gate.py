from __future__ import annotations

from pathlib import Path

import pytest

from scripts.mutation_gate import (
    MutationCase,
    apply_text_mutation,
    build_mutation_cases,
    unique_tests,
)


def test_ci_mode_includes_the_core_mutation_cases():
    cases = build_mutation_cases("ci")
    names = [case.name for case in cases]

    assert names == [
        "health-status-code",
        "health-preflight-status-code",
        "tools-confirmation-policy",
        "context-prune-threshold",
        "preflight-optional-integrations",
        "unified-search-min-score",
        "entity-extractor-fallback-loop",
        "evaluation-contract-drift",
    ]


def test_nightly_mode_extends_ci_with_extra_cases():
    ci_cases = build_mutation_cases("ci")
    nightly_cases = build_mutation_cases("nightly")

    assert len(nightly_cases) > len(ci_cases)
    assert {case.name for case in ci_cases}.issubset({case.name for case in nightly_cases})


def test_unique_tests_deduplicates_and_sorts():
    cases = (
        MutationCase(
            name="a",
            target=Path("a.py"),
            before="one",
            after="two",
            tests=("tests/unit/test_b.py", "tests/unit/test_a.py"),
            description="one",
        ),
        MutationCase(
            name="b",
            target=Path("b.py"),
            before="three",
            after="four",
            tests=("tests/unit/test_a.py",),
            description="two",
        ),
    )

    assert unique_tests(cases) == (
        "tests/unit/test_a.py",
        "tests/unit/test_b.py",
    )


def test_apply_text_mutation_replaces_one_exact_block(tmp_path: Path):
    target = tmp_path / "example.py"
    target.write_text("alpha\nbeta\nalpha\n", encoding="utf-8")

    apply_text_mutation(target, "alpha", "gamma")

    assert target.read_text(encoding="utf-8") == "gamma\nbeta\nalpha\n"


def test_apply_text_mutation_errors_when_block_is_missing(tmp_path: Path):
    target = tmp_path / "example.py"
    target.write_text("alpha\nbeta\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Mutation pattern not found"):
        apply_text_mutation(target, "missing", "gamma")

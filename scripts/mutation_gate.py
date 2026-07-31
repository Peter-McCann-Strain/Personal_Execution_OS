"""Run a focused mutation-testing gate for critical backend modules.

The runner keeps the workflow practical by:
- cloning ``src/`` into a temporary tree,
- applying a small curated set of source mutations,
- executing the most relevant unit tests for each mutation, and
- failing when a mutant survives unexpectedly.

Usage:
    uv run python -m scripts.mutation_gate --mode ci
    uv run python -m scripts.mutation_gate --mode nightly
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from subprocess import CompletedProcess, run

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
TESTS_ROOT = REPO_ROOT / "tests"
DATA_ROOT = REPO_ROOT / "data"
CONFIG_ROOT = REPO_ROOT / "config"


@dataclass(frozen=True, slots=True)
class MutationCase:
    """A single source mutation plus the tests that should kill it."""

    name: str
    target: Path
    before: str
    after: str
    tests: tuple[str, ...]
    description: str


def _block(text: str) -> str:
    """Normalize a multiline string block for exact replacement."""
    return text.strip("\n")


def _snippet(*lines: str) -> str:
    """Build an exact multiline snippet from explicit source lines."""
    return "\n".join(lines)


def _mutation_cases() -> dict[str, tuple[MutationCase, ...]]:
    """Return the mutation suites for each execution mode."""
    ci_cases = (
        MutationCase(
            name="health-status-code",
            target=Path("app/api/routes/health.py"),
            before=_snippet(
                '    status_code = 200 if overall != "down" else 503',
            ),
            after=_snippet(
                '    status_code = 503 if overall != "down" else 200',
            ),
            tests=("tests/unit/test_health_endpoint.py",),
            description="Flip the health response code gate so degraded/healthy routing is wrong.",
        ),
        MutationCase(
            name="health-preflight-status-code",
            target=Path("app/api/routes/health.py"),
            before=_snippet(
                '    status_code = 200 if report.status != "fail" else 503',
            ),
            after=_snippet(
                '    status_code = 503 if report.status != "fail" else 200',
            ),
            tests=("tests/integration/test_api_endpoints.py",),
            description="Invert /health/preflight status mapping.",
        ),
        MutationCase(
            name="tools-confirmation-policy",
            target=Path("app/domain/services/handlers/tools.py"),
            before=_snippet(
                "    if runtime_config.confirmation_policy != ConfirmationPolicy.ON_MUTATION:",
                "        return False",
            ),
            after=_snippet(
                "    if runtime_config.confirmation_policy == ConfirmationPolicy.ON_MUTATION:",
                "        return False",
            ),
            tests=("tests/unit/handlers/test_tools_handler.py",),
            description="Invert the confirmation-policy guard for mutating tools.",
        ),
        MutationCase(
            name="context-prune-threshold",
            target=Path("app/core/context_engine.py"),
            before=_snippet(
                "            should_prune = (",
                "                idx not in protected_indexes",
                '                and msg.get("role") == "assistant"',
                '                and msg.get("agent") == "tools"',
                "                and len(content) > 4_000",
                "            )",
            ),
            after=_snippet(
                "            should_prune = (",
                "                idx not in protected_indexes",
                '                and msg.get("role") == "assistant"',
                '                and msg.get("agent") == "tools"',
                "                and len(content) < 4_000",
                "            )",
            ),
            tests=("tests/unit/test_context_engine.py",),
            description="Break the oversized tool-output pruning threshold.",
        ),
        MutationCase(
            name="preflight-optional-integrations",
            target=Path("app/core/preflight.py"),
            before=_snippet(
                "    if missing_servers:",
            ),
            after=_snippet(
                "    if not missing_servers:",
            ),
            tests=("tests/unit/test_preflight.py",),
            description="Invert optional integration readiness for missing servers.",
        ),
        MutationCase(
            name="unified-search-min-score",
            target=Path("app/persistence/repositories/unified_search.py"),
            before=_snippet(
                "    filtered = [r for r in merged if r.score >= min_score][:limit]",
            ),
            after=_snippet(
                "    filtered = [r for r in merged if r.score <= min_score][:limit]",
            ),
            tests=("tests/unit/repositories/test_unified_search.py",),
            description="Invert the minimum-score filter for fused retrieval results.",
        ),
        MutationCase(
            name="entity-extractor-fallback-loop",
            target=Path("app/second_brain/entity_extractor.py"),
            before=_snippet(
                '        for ent in data.get("entities", []):',
                (
                    '            if isinstance(ent, dict) and "name" in ent '
                    'and "entity_type" in ent:'
                ),
                "                try:",
                "                    entities.append(ExtractedEntity(**ent))",
                "                except ValueError:",
                "                    continue",
            ),
            after=_snippet(
                '        for ent in data.get("entities", []):',
                (
                    '            if isinstance(ent, dict) and "name" in ent '
                    'and "entity_type" in ent:'
                ),
                "                try:",
                "                    entities.append(ExtractedEntity(**ent))",
                "                except ValueError:",
                "                    return ExtractionResult(",
                "                        entities=entities,",
                "                        relationships=relationships,",
                "                    )",
            ),
            tests=("tests/unit/test_entity_extractor.py",),
            description="Stop fallback validation after the first malformed entity.",
        ),
        MutationCase(
            name="evaluation-contract-drift",
            target=Path("app/core/evaluation_registry.py"),
            before=_snippet(
                "    if dataset.rubric_id != runtime.eval_rubric_id:",
            ),
            after=_snippet(
                "    if dataset.rubric_id == runtime.eval_rubric_id:",
            ),
            tests=("tests/unit/test_evaluation_registry.py",),
            description="Disable the runtime/dataset rubric drift guard.",
        ),
    )

    nightly_extras = (
        MutationCase(
            name="unified-search-overfetch",
            target=Path("app/persistence/repositories/unified_search.py"),
            before=_snippet(
                "    sub_limit = limit * 2  # over-fetch so RRF has enough candidates",
            ),
            after=_snippet(
                "    sub_limit = limit  # over-fetch so RRF has enough candidates",
            ),
            tests=("tests/unit/repositories/test_unified_search.py",),
            description="Remove the over-fetch buffer that feeds the fusion ranking.",
        ),
        MutationCase(
            name="health-cache-ttl",
            target=Path("app/api/routes/health.py"),
            before=_snippet("_CACHE_TTL_SECONDS = 10.0"),
            after=_snippet("_CACHE_TTL_SECONDS = 0.0"),
            tests=("tests/unit/test_health_endpoint.py",),
            description="Disable health-response caching and force the cache tests to fail.",
        ),
    )

    return {
        "ci": ci_cases,
        "nightly": ci_cases + nightly_extras,
    }


def build_mutation_cases(mode: str) -> tuple[MutationCase, ...]:
    """Return the mutation cases for the requested mode."""
    suites = _mutation_cases()
    try:
        return suites[mode]
    except KeyError as exc:  # pragma: no cover - guarded by argparse
        raise ValueError(f"Unknown mutation mode: {mode}") from exc


def unique_tests(cases: tuple[MutationCase, ...]) -> tuple[str, ...]:
    """Collect all unique tests needed to validate a suite."""
    return tuple(sorted({test for case in cases for test in case.tests}))


def prepare_temp_src(temp_root: Path) -> Path:
    """Clone the source tree into a writable temporary worktree."""
    temp_src = temp_root / "src"
    shutil.copytree(SRC_ROOT, temp_src)
    shutil.copytree(TESTS_ROOT, temp_root / "tests")
    if DATA_ROOT.exists():
        shutil.copytree(DATA_ROOT, temp_root / "data")
    if CONFIG_ROOT.exists():
        shutil.copytree(CONFIG_ROOT, temp_root / "config")
    return temp_src


def apply_text_mutation(file_path: Path, before: str, after: str) -> None:
    """Apply a single exact-text mutation in-place."""
    current = file_path.read_text(encoding="utf-8")
    if before not in current:
        raise ValueError(f"Mutation pattern not found in {file_path}")
    mutated = current.replace(before, after, 1)
    if mutated == current:
        raise ValueError(f"Mutation pattern did not change {file_path}")
    file_path.write_text(mutated, encoding="utf-8")


def run_pytest(temp_root: Path, tests: tuple[str, ...]) -> CompletedProcess[int]:
    """Run pytest against the mutated tree."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(temp_root)
    command = [sys.executable, "-m", "pytest", "-q", "--asyncio-mode=auto", *tests]
    return run(command, cwd=temp_root, env=env, check=False)


def run_suite(mode: str) -> int:
    """Execute the selected mutation suite and print a concise report."""
    cases = build_mutation_cases(mode)
    baseline_tests = unique_tests(cases)

    print(f"Running mutation gate in {mode!r} mode")
    print(f"Baseline validation tests: {', '.join(baseline_tests)}")

    with tempfile.TemporaryDirectory(prefix="mutation-gate-") as temp_dir:
        temp_root = Path(temp_dir)
        prepare_temp_src(temp_root)

        baseline = run_pytest(temp_root, baseline_tests)
        if baseline.returncode != 0:
            print("ERROR: Baseline validation tests failed before mutation checks ran.")
            return baseline.returncode

        survivors: list[MutationCase] = []
        killed: list[MutationCase] = []

        for index, case in enumerate(cases):
            case_root = temp_root / f"case-{index}-{case.name}"
            case_root.mkdir()
            shutil.copytree(temp_root / "src", case_root / "src")
            shutil.copytree(temp_root / "tests", case_root / "tests")
            if (temp_root / "config").exists():
                shutil.copytree(temp_root / "config", case_root / "config")
            mut_file = case_root / "src" / case.target
            apply_text_mutation(mut_file, case.before, case.after)

            print(f"- {case.name}: {case.description}")
            result = run_pytest(case_root, case.tests)
            if result.returncode == 0:
                survivors.append(case)
                print(f"  SURVIVED: {case.name}")
            else:
                killed.append(case)
                print(f"  killed by: {', '.join(case.tests)}")

        print()
        print("## Mutation Gate Summary")
        print(f"- Baseline tests: {len(baseline_tests)}")
        print(f"- Mutations killed: {len(killed)}")
        print(f"- Mutations survived: {len(survivors)}")

        if survivors:
            print("- Surviving mutations:")
            for case in survivors:
                print(f"  - {case.name} ({case.target})")
            return 1

        return 0


def build_parser() -> argparse.ArgumentParser:
    """Construct the CLI parser."""
    parser = argparse.ArgumentParser(description="Run the backend mutation gate.")
    parser.add_argument(
        "--mode",
        choices=("ci", "nightly"),
        default="ci",
        help="Mutation suite to run. Nightly includes the CI cases plus extra checks.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List the selected mutation cases and exit.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    args = build_parser().parse_args(argv)
    cases = build_mutation_cases(args.mode)

    if args.list:
        for case in cases:
            print(f"{case.name}: {case.target} -> {case.tests}")
        return 0

    return run_suite(args.mode)


if __name__ == "__main__":
    raise SystemExit(main())

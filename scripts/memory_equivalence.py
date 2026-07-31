"""CLI for deterministic state-packet memory-equivalence checks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.app.core.memory_equivalence import (
    load_memory_equivalence_dataset,
    run_memory_equivalence_dataset,
)


def build_parser() -> argparse.ArgumentParser:
    """Build CLI parser."""
    parser = argparse.ArgumentParser(
        description="Run deterministic compacted-memory equivalence checks.",
    )
    parser.add_argument(
        "--dataset",
        default="data/evaluation/datasets/memory_equivalence.v1.json",
        help="Path to the memory-equivalence dataset JSON file.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full result as JSON.",
    )
    return parser


def main() -> None:
    """CLI entrypoint."""
    args = build_parser().parse_args()
    dataset = load_memory_equivalence_dataset(Path(args.dataset))
    report = run_memory_equivalence_dataset(dataset)

    if args.json:
        print(json.dumps(report.model_dump(mode="json"), indent=2))
    else:
        print(
            f"Memory equivalence: {report.average_coverage:.3f} "
            f"(threshold {report.minimum_average_coverage:.3f})"
        )
        for case in report.cases:
            status = "PASS" if case.passed else "FAIL"
            print(f"- {case.id}: {status} ({case.coverage:.3f})")

    raise SystemExit(0 if report.passed else 1)


if __name__ == "__main__":
    main()

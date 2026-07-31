"""Summarize Cobertura coverage XML and optionally enforce thresholds.

Usage:
    uv run python -m scripts.coverage_summary --xml coverage.xml
    uv run python -m scripts.coverage_summary --xml coverage.xml --min-line-rate 0.9
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class FileCoverage:
    """Coverage metrics for a single file."""

    filename: str
    line_rate: float
    branch_rate: float


@dataclass(slots=True)
class CoverageSummary:
    """Top-level coverage summary plus per-file metrics."""

    line_rate: float
    branch_rate: float
    lines_covered: int
    lines_valid: int
    branches_covered: int
    branches_valid: int
    files: list[FileCoverage]


def parse_coverage_xml(path: Path) -> CoverageSummary:
    """Parse a coverage.py Cobertura XML report."""
    root = ET.parse(path).getroot()  # noqa: S314 - parses a locally generated CI artifact

    files: list[FileCoverage] = []
    for class_node in root.findall(".//class"):
        filename = class_node.attrib.get("filename")
        if not filename:
            continue
        files.append(
            FileCoverage(
                filename=filename,
                line_rate=float(class_node.attrib.get("line-rate", "0")),
                branch_rate=float(class_node.attrib.get("branch-rate", "0")),
            )
        )

    return CoverageSummary(
        line_rate=float(root.attrib.get("line-rate", "0")),
        branch_rate=float(root.attrib.get("branch-rate", "0")),
        lines_covered=int(root.attrib.get("lines-covered", "0")),
        lines_valid=int(root.attrib.get("lines-valid", "0")),
        branches_covered=int(root.attrib.get("branches-covered", "0")),
        branches_valid=int(root.attrib.get("branches-valid", "0")),
        files=sorted(files, key=lambda item: (item.line_rate, item.branch_rate, item.filename)),
    )


def render_summary(
    summary: CoverageSummary,
    *,
    min_line_rate: float | None,
    min_branch_rate: float | None,
    top: int,
) -> str:
    """Render a markdown summary suitable for CI logs or GitHub step summaries."""
    lines = [
        "## Coverage Summary",
        "",
        f"- Line coverage: {summary.line_rate * 100:.2f}% "
        f"({summary.lines_covered}/{summary.lines_valid})",
        f"- Branch coverage: {summary.branch_rate * 100:.2f}% "
        f"({summary.branches_covered}/{summary.branches_valid})",
    ]

    if min_line_rate is not None:
        lines.append(f"- Minimum line coverage gate: {min_line_rate * 100:.2f}%")
    if min_branch_rate is not None:
        lines.append(f"- Minimum branch coverage gate: {min_branch_rate * 100:.2f}%")

    lines.extend(
        [
            "",
            "### Lowest Coverage Files",
            "",
            "| File | Line | Branch |",
            "| --- | ---: | ---: |",
        ]
    )

    for item in summary.files[:top]:
        lines.append(
            f"| `{item.filename}` | {item.line_rate * 100:.2f}% | {item.branch_rate * 100:.2f}% |"
        )

    return "\n".join(lines)


def enforce_thresholds(
    summary: CoverageSummary,
    *,
    min_line_rate: float | None,
    min_branch_rate: float | None,
) -> list[str]:
    """Return any threshold failures."""
    failures: list[str] = []
    if min_line_rate is not None and summary.line_rate < min_line_rate:
        failures.append(
            f"Line coverage {summary.line_rate * 100:.2f}% is below the required "
            f"{min_line_rate * 100:.2f}%."
        )
    if min_branch_rate is not None and summary.branch_rate < min_branch_rate:
        failures.append(
            f"Branch coverage {summary.branch_rate * 100:.2f}% is below the required "
            f"{min_branch_rate * 100:.2f}%."
        )
    return failures


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Summarize coverage XML and enforce thresholds.",
    )
    parser.add_argument(
        "--xml",
        type=Path,
        required=True,
        help="Path to Cobertura XML coverage file.",
    )
    parser.add_argument(
        "--min-line-rate",
        type=float,
        default=None,
        help="Minimum overall line coverage as a ratio, for example 0.90.",
    )
    parser.add_argument(
        "--min-branch-rate",
        type=float,
        default=None,
        help="Minimum overall branch coverage as a ratio, for example 0.85.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=12,
        help="Number of lowest-coverage files to include in the summary table.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    args = build_parser().parse_args(argv)
    summary = parse_coverage_xml(args.xml)

    print(
        render_summary(
            summary,
            min_line_rate=args.min_line_rate,
            min_branch_rate=args.min_branch_rate,
            top=args.top,
        )
    )

    failures = enforce_thresholds(
        summary,
        min_line_rate=args.min_line_rate,
        min_branch_rate=args.min_branch_rate,
    )
    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

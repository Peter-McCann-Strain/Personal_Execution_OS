"""Scan every line of a log for PII shapes without reproducing matched values.

The report contains only categories and line numbers. It deliberately omits
excerpts, hashes, and parsed payloads because even transformed identifiers can
be sensitive or easy to recover from a small search space.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_CHECKS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "email",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    ),
    (
        "phone",
        re.compile(r"(?<!\w)(?:\+?[1-9]\d{0,2}[\s().-]?)?(?:\d[\s().-]?){8,14}(?!\w)"),
    ),
    (
        "uk_postcode",
        re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", re.IGNORECASE),
    ),
    (
        "payment_card",
        re.compile(r"\b(?:\d[ -]?){13,19}\b"),
    ),
    (
        "private_key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    (
        "bearer_token",
        re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}\b", re.IGNORECASE),
    ),
)


@dataclass(frozen=True)
class Finding:
    category: str
    line_number: int


def scan_file(path: Path) -> tuple[int, list[Finding]]:
    findings: list[Finding] = []
    line_count = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_count, line in enumerate(handle, start=1):
            for category, pattern in _CHECKS:
                if pattern.search(line):
                    findings.append(Finding(category, line_count))
    return line_count, findings


def render_report(
    *,
    log_name: str,
    total_lines: int,
    findings: list[Finding],
    generated_at: datetime,
) -> str:
    counts = Counter(finding.category for finding in findings)
    lines = [
        "# PII Redaction Audit",
        "",
        f"- Generated: {generated_at.isoformat()}",
        f"- Input name: `{log_name}`",
        f"- Lines scanned: {total_lines}",
        f"- Verdict: {'FAIL' if findings else 'PASS'}",
        "",
        "## Category counts",
        "",
    ]
    if counts:
        lines.extend(f"- `{category}`: {count}" for category, count in sorted(counts.items()))
    else:
        lines.append("- none")

    lines.extend(["", "## Locations", ""])
    if findings:
        lines.extend(f"- line {finding.line_number}: `{finding.category}`" for finding in findings)
    else:
        lines.append("- No PII-shaped values detected.")

    lines.extend(
        [
            "",
            "The report intentionally contains no excerpts or value fingerprints.",
            "If the verdict is FAIL, inspect the source log privately, fix the",
            "logging path, rotate any exposed credential, and delete unsafe copies.",
            "",
        ]
    )
    return "\n".join(lines)


def run(*, log_path: Path, out_path: Path) -> int:
    if not log_path.is_file():
        raise SystemExit("log file not found")
    total_lines, findings = scan_file(log_path)
    report = render_report(
        log_name=log_path.name,
        total_lines=total_lines,
        findings=findings,
        generated_at=datetime.now(UTC),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    return 1 if findings else 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a value-redacting full log PII audit.")
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/pii_audit/report.md"),
    )
    parser.add_argument(
        "--samples",
        type=int,
        help="Deprecated compatibility option; the scanner always checks every line.",
    )
    parser.add_argument("--seed", type=int, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    return run(log_path=args.log, out_path=args.out)


if __name__ == "__main__":
    sys.exit(main())

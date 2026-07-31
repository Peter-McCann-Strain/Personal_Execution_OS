"""Local provider readiness checks for external API attachment."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from src.app.config import get_settings
from src.app.core.preflight import PreflightCheck, run_startup_preflight


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(
        description="Validate external provider readiness from configuration and runtime checks.",
    )
    parser.add_argument(
        "--include-runtime-checks",
        action="store_true",
        help="Include runtime checks such as Redis connectivity and database extensions.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full preflight report as JSON.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return a non-zero exit code on warn as well as fail.",
    )
    return parser


def _provider_check(report_checks: list[PreflightCheck]) -> PreflightCheck | None:
    """Extract the provider configuration check from a preflight report."""
    for check in report_checks:
        if check.name == "provider_configuration":
            return check
    return None


def _render_text_report(report: dict[str, Any]) -> str:
    """Render a concise human-readable readiness summary."""
    checks = report.get("checks", [])
    provider_check = next(
        (check for check in checks if check.get("name") == "provider_configuration"),
        None,
    )
    lines = [f"Provider readiness: {report['status']}"]

    if provider_check is None:
        lines.append("- provider configuration: unavailable")
        return "\n".join(lines)

    details = provider_check.get("details", {})
    required = details.get("required", {})
    optional = details.get("optional", {})
    missing_required = details.get("missing_required", [])
    missing_optional = details.get("missing_optional", [])

    lines.append(f"- required configured: {sum(required.values())}/{len(required)}")
    if missing_required:
        lines.append(f"- missing required: {', '.join(missing_required)}")
    else:
        lines.append("- missing required: none")

    enabled_optional = [name for name, configured in optional.items() if configured]
    lines.append(
        "- enabled optional: " + (", ".join(enabled_optional) if enabled_optional else "none"),
    )
    if missing_optional:
        lines.append(f"- missing optional: {', '.join(missing_optional)}")

    return "\n".join(lines)


async def _main_async(args: argparse.Namespace) -> int:
    settings = get_settings()
    report = await run_startup_preflight(
        settings=settings,
        include_runtime_checks=args.include_runtime_checks,
    )
    payload = report.model_dump(mode="json")

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(_render_text_report(payload))

    if report.status == "fail":
        return 1
    if args.strict and report.status == "warn":
        return 1
    return 0


def main() -> None:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main_async(args)))

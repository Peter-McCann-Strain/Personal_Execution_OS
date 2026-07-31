#!/usr/bin/env python3
"""Refresh numeric claims in CLAUDE.md by re-counting source-of-truth artefacts.

Run from repo root: python scripts/refresh_claude_md.py

Exit codes:
    0 — file changed (stale claims rewritten)
    1 — no changes needed (claims already accurate)
    2 — error (missing repo, regex mismatch, IO failure)
"""

from __future__ import annotations

import datetime as _dt
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
CONFIG_PY = REPO_ROOT / "src" / "app" / "config.py"


def collect_counts() -> dict[str, int | str]:
    """Compute the canonical numeric claims from the live filesystem."""
    test_paths = list((REPO_ROOT / "tests").rglob("*.py"))
    test_pattern = re.compile(r"^(?: {4})?(?:async )?def test_", re.MULTILINE)
    test_files = len(test_paths)
    test_funcs = sum(
        len(test_pattern.findall(path.read_text(encoding="utf-8"))) for path in test_paths
    )
    route_modules = sum(
        path.name != "__init__.py"
        for path in (REPO_ROOT / "src" / "app" / "api" / "routes").rglob("*.py")
    )
    repos = sum(
        path.name != "__init__.py"
        for path in (REPO_ROOT / "src" / "app" / "persistence" / "repositories").rglob("*.py")
    )
    frontend_files = sum(
        path.suffix in {".ts", ".tsx"} for path in (REPO_ROOT / "frontend" / "src").rglob("*")
    )
    auto_judge_model = _extract_config_str("auto_judge_model")
    return {
        "test_files": test_files,
        "test_funcs": test_funcs,
        "route_modules": route_modules,
        "repos": repos,
        "frontend_files": frontend_files,
        "auto_judge_model": auto_judge_model,
    }


def _extract_config_str(name: str) -> str:
    """Pull a `name: str = "value"` literal out of config.py."""
    text = CONFIG_PY.read_text(encoding="utf-8")
    match = re.search(rf'^\s*{re.escape(name)}\s*:\s*str\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise RuntimeError(f"could not find {name} in {CONFIG_PY}")
    return match.group(1)


# Each rule: (label, compiled regex over a single line, replacement template)
# Replacement template uses {value} placeholders filled from `counts`.
RULES: list[tuple[str, re.Pattern[str], str, str]] = [
    (
        "route_modules",
        re.compile(r"HTTP layer \(\d+ route modules"),
        "HTTP layer ({route_modules} route modules",
        "route_modules",
    ),
    (
        "repos",
        re.compile(r"SQLAlchemy ORM, \d+ repositories"),
        "SQLAlchemy ORM, {repos} repositories",
        "repos",
    ),
    (
        "frontend_files",
        re.compile(r"React \+ TypeScript \+ Vite dashboard \(\d+ files\)"),
        "React + TypeScript + Vite dashboard ({frontend_files} files)",
        "frontend_files",
    ),
    (
        "tests_summary",
        re.compile(r"tests/\s+— \d+ tests across \d+ files"),
        "tests/                 — {test_funcs} tests across {test_files} files",
        "test_funcs+test_files",
    ),
    (
        "auto_judge",
        re.compile(r"\(Sonnet [\d.]+ auto-judge[^)]*\)|\(Haiku auto-judge[^)]*\)"),
        "(Sonnet 4.6 auto-judge — see `config.py`. Cost scales with interaction volume.)",
        "auto_judge_model",
    ),
]

LAST_VERIFIED_RE = re.compile(r"^\*\*Last verified:\*\* \d{4}-\d{2}-\d{2}.*$", re.MULTILINE)


def apply_rewrite(text: str, counts: dict[str, int | str]) -> tuple[str, list[str]]:
    """Apply all replacement rules and stamp Last verified. Returns (new_text, edits)."""
    edits: list[str] = []
    new_text = text

    for label, pattern, template, _ in RULES:
        replacement = template.format(**counts)
        match = pattern.search(new_text)
        if not match:
            edits.append(f"WARN: rule '{label}' matched nothing — claim may be missing")
            continue
        existing = match.group(0)
        if existing == replacement:
            continue
        new_text = pattern.sub(replacement, new_text, count=1)
        edits.append(f"{label}: {existing!r} -> {replacement!r}")

    today = _dt.date.today().isoformat()
    stamp = f"**Last verified:** {today} via scripts/refresh_claude_md.py"
    existing_stamp = LAST_VERIFIED_RE.search(new_text)
    if existing_stamp is not None:
        if existing_stamp.group(0) != stamp:
            new_text = LAST_VERIFIED_RE.sub(stamp, new_text, count=1)
            edits.append(f"Last verified -> {today}")
    else:
        new_text = new_text.rstrip() + "\n\n" + stamp + "\n"
        edits.append(f"Last verified appended: {today}")

    return new_text, edits


def main() -> int:
    if not CLAUDE_MD.exists():
        print(f"ERROR: {CLAUDE_MD} not found", file=sys.stderr)
        return 2
    if not CONFIG_PY.exists():
        print(f"ERROR: {CONFIG_PY} not found", file=sys.stderr)
        return 2

    try:
        counts = collect_counts()
    except Exception as exc:
        print(f"ERROR collecting counts: {exc}", file=sys.stderr)
        return 2

    print("Verified counts:")
    for k, v in counts.items():
        print(f"  {k}: {v}")

    original = CLAUDE_MD.read_text(encoding="utf-8")
    try:
        new_text, edits = apply_rewrite(original, counts)
    except Exception as exc:
        print(f"ERROR rewriting: {exc}", file=sys.stderr)
        return 2

    if new_text == original:
        print("\nNo changes needed — CLAUDE.md is already accurate.")
        return 1

    CLAUDE_MD.write_text(new_text, encoding="utf-8")
    print("\nEdits applied to CLAUDE.md:")
    for edit in edits:
        print(f"  - {edit}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

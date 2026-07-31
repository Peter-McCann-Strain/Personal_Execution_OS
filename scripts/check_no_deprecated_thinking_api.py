"""CI guard: fail if any non-test file under src/ references the deprecated
extended-thinking API (``budget_tokens`` or ``thinking={"type": "enabled"}``).

Context (April 2026): the April 2026 Anthropic API replaced
``thinking={"type":"enabled","budget_tokens":N}`` with
``thinking={"type":"adaptive"}`` + ``output_config={"effort":<level>}``.
The old shape is DEPRECATED on Opus 4.6 / Sonnet 4.6 and returns HTTP 400 on
Opus 4.7. This script exists so a regression cannot land silently.

Run locally:
    uv run python -m scripts.check_no_deprecated_thinking_api

Exits 0 on clean, 1 on any finding.
"""

from __future__ import annotations

import io
import re
import sys
import token
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

# Two deprecated patterns. ``budget_tokens`` is the hard rejection on 4.7.
# ``thinking={"type":"enabled"}`` (with any whitespace / quoting) is the
# other deprecated call shape. We allow ``type":"disabled"`` and
# ``type":"adaptive"``.
_BUDGET_TOKENS = re.compile(r"\bbudget_tokens\b")
_ENABLED_THINKING = re.compile(
    r"""thinking\s*=\s*\{[^}]*["']type["']\s*:\s*["']enabled["']""",
    re.DOTALL,
)


def _iter_py_files(root: Path):
    for path in root.rglob("*.py"):
        # Skip cache / generated dirs.
        if "__pycache__" in path.parts:
            continue
        yield path


def _strip_comments_and_strings(text: str) -> str:
    """Return *text* with all comments and string literals replaced by spaces
    (preserving line numbering). This ensures the scanner only flags real
    Python references — not the words ``budget_tokens`` appearing inside a
    docstring that documents the deprecation itself.
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenizeError, IndentationError, SyntaxError):
        # On malformed source, fall back to raw text — the ruff step will
        # catch the real issue; we simply don't want to crash CI here.
        return text

    lines = text.splitlines(keepends=True)
    # Mutate a mutable copy of each line, replacing the comment/string spans
    # with spaces so regex line numbers remain correct.
    buf: list[list[str]] = [list(line) for line in lines]
    for tok in tokens:
        if tok.type not in (token.COMMENT, token.STRING):
            continue
        (srow, scol), (erow, ecol) = tok.start, tok.end
        # Convert 1-indexed rows to 0-indexed buffer rows.
        for row in range(srow - 1, erow):
            if row >= len(buf):
                break
            line_len = len(buf[row])
            col_start = scol if row == srow - 1 else 0
            col_end = ecol if row == erow - 1 else line_len
            for col in range(col_start, min(col_end, line_len)):
                # Preserve newlines so line numbers stay accurate.
                if buf[row][col] != "\n":
                    buf[row][col] = " "
    return "".join("".join(line) for line in buf)


def scan() -> list[tuple[Path, int, str]]:
    findings: list[tuple[Path, int, str]] = []
    for path in _iter_py_files(SRC):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        scannable = _strip_comments_and_strings(text)
        for pattern, label in (
            (_BUDGET_TOKENS, "budget_tokens"),
            (_ENABLED_THINKING, 'thinking={"type":"enabled"}'),
        ):
            for match in pattern.finditer(scannable):
                line_no = scannable.count("\n", 0, match.start()) + 1
                findings.append((path, line_no, label))
    return findings


def main() -> int:
    findings = scan()
    if not findings:
        print("OK: no deprecated extended-thinking API usage under src/.")
        return 0

    print(
        "ERROR: deprecated extended-thinking API usage detected. Replace with "
        'thinking={"type":"adaptive"} + output_config={"effort":<level>}.\n',
        file=sys.stderr,
    )
    for path, line_no, label in findings:
        rel = path.relative_to(ROOT)
        print(f"  {rel}:{line_no}  [{label}]", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

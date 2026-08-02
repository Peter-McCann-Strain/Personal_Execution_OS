"""Validate the repository's hand-written Markdown documentation.

The checker is intentionally dependency-free. Markdown style and Mermaid
rendering are separate CI steps; this script owns repository-specific
correctness rules that a generic linter cannot infer.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

REQUIRED_DOCUMENTS = {
    Path("CHANGELOG.md"),
    Path("CODE_OF_CONDUCT.md"),
    Path("GOVERNANCE.md"),
    Path("README.md"),
    Path("SECURITY.md"),
    Path("SUPPORT.md"),
    Path("CONTRIBUTING.md"),
    Path("docs/README.md"),
    Path("docs/SETUP.md"),
    Path("docs/ARCHITECTURE.md"),
    Path("docs/CAPABILITIES.md"),
    Path("docs/FIRST_TEN_MINUTES.md"),
    Path("docs/PRODUCT_SCOPE.md"),
    Path("docs/ROADMAP.md"),
    Path("docs/DEVELOPER_GUIDE.md"),
    Path("docs/API.md"),
    Path("docs/CONFIGURATION.md"),
    Path("docs/OBSERVABILITY.md"),
    Path("docs/ACCESSIBILITY.md"),
    Path("docs/PRIVACY.md"),
    Path("docs/INTEGRATIONS.md"),
    Path("docs/decisions/README.md"),
    Path("frontend/README.md"),
    Path("tests/integration/README.md"),
}

# These paths are intentionally created from tracked templates during setup and
# must remain ignored rather than committed.
EXPECTED_PRIVATE_PATHS = {
    "config/IDENTITY.local.md",
}

MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*]\((?P<target><[^>]+>|[^)\s]+)(?:\s+[^)]*)?\)")
HEADING_RE = re.compile(r"^#{1,6}\s+(?P<title>.+?)\s*#*\s*$")
HTML_TAG_RE = re.compile(r"<[^>]+>")
INLINE_MARKUP_RE = re.compile(r"[`*_~]")
SOURCE_PATH_RE = re.compile(
    r"`(?P<path>(?:src|frontend|tests|scripts|docs|data|config|docker|\.github)/[^`\s]+)`"
)


@dataclass(frozen=True)
class Problem:
    path: Path
    line: int
    message: str

    def render(self, root: Path) -> str:
        try:
            relative = self.path.relative_to(root)
        except ValueError:
            relative = self.path
        return f"{relative}:{self.line}: {self.message}"


def _markdown_files(root: Path) -> list[Path]:
    excluded_parts = {".git", ".venv", "node_modules"}
    return sorted(
        path
        for path in root.rglob("*.md")
        if not excluded_parts.intersection(path.relative_to(root).parts)
    )


def _slug_base(title: str) -> str:
    title = HTML_TAG_RE.sub("", title)
    title = INLINE_MARKUP_RE.sub("", title).strip().lower()
    title = re.sub(r"[^\w\- ]", "", title, flags=re.UNICODE)
    return re.sub(r"\s+", "-", title)


def _anchors(lines: list[str]) -> set[str]:
    anchors: set[str] = set()
    counts: defaultdict[str, int] = defaultdict(int)
    in_fence = False
    fence_char = ""

    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            if not in_fence:
                in_fence = True
                fence_char = marker
            elif marker == fence_char:
                in_fence = False
            continue
        if in_fence:
            continue

        match = HEADING_RE.match(line)
        if not match:
            continue
        base = _slug_base(match.group("title"))
        suffix = counts[base]
        counts[base] += 1
        anchors.add(base if suffix == 0 else f"{base}-{suffix}")
    return anchors


def _split_local_target(raw_target: str) -> tuple[str, str]:
    target = raw_target[1:-1] if raw_target.startswith("<") else raw_target
    decoded = unquote(target)
    if "#" not in decoded:
        return decoded, ""
    path, fragment = decoded.split("#", 1)
    return path, fragment.lower()


def _source_path(raw: str) -> str | None:
    candidate = raw.rstrip(".,;:)")
    if any(token in candidate for token in ("*", "<", ">", "{", "}")):
        return None

    # Symbol notation such as ``src/app/main.py:create_app`` is documentation
    # syntax, not part of the filesystem path.
    file_part = candidate.split(":", 1)[0]
    return file_part


def check_documentation(root: Path) -> list[Problem]:
    root = root.resolve()
    problems: list[Problem] = []
    markdown_files = _markdown_files(root)
    line_cache: dict[Path, list[str]] = {}
    anchor_cache: dict[Path, set[str]] = {}

    for relative in sorted(REQUIRED_DOCUMENTS):
        target = root / relative
        if not target.is_file():
            problems.append(Problem(target, 1, "required documentation file is missing"))

    for path in markdown_files:
        lines = path.read_text(encoding="utf-8").splitlines()
        line_cache[path] = lines
        anchor_cache[path] = _anchors(lines)

        fence: tuple[str, int, str] | None = None
        mermaid_content = 0
        for line_number, line in enumerate(lines, start=1):
            stripped = line.lstrip()
            if stripped.startswith(("```", "~~~")):
                marker = stripped[:3]
                language = stripped[3:].strip().lower()
                if fence is None:
                    fence = (marker, line_number, language)
                    mermaid_content = 0
                elif marker == fence[0]:
                    if fence[2] == "mermaid" and mermaid_content == 0:
                        problems.append(
                            Problem(path, fence[1], "Mermaid code fence must not be empty")
                        )
                    fence = None
                continue
            if fence is not None:
                if fence[2] == "mermaid" and stripped:
                    mermaid_content += 1
                continue

            for match in MARKDOWN_LINK_RE.finditer(line):
                raw_target = match.group("target")
                candidate = raw_target[1:-1] if raw_target.startswith("<") else raw_target
                parsed = urlsplit(candidate)
                if parsed.scheme or candidate.startswith(("//", "mailto:", "tel:")):
                    continue

                relative_target, fragment = _split_local_target(raw_target)
                target = (
                    path if relative_target == "" else (path.parent / relative_target).resolve()
                )
                if not target.exists():
                    problems.append(
                        Problem(
                            path,
                            line_number,
                            f"local link target does not exist: {raw_target}",
                        )
                    )
                    continue
                if fragment and target.suffix.lower() == ".md":
                    target_lines = line_cache.setdefault(
                        target, target.read_text(encoding="utf-8").splitlines()
                    )
                    target_anchors = anchor_cache.setdefault(target, _anchors(target_lines))
                    if fragment not in target_anchors:
                        problems.append(
                            Problem(
                                path,
                                line_number,
                                f"Markdown anchor does not exist: {raw_target}",
                            )
                        )

            for match in SOURCE_PATH_RE.finditer(line):
                source_path = _source_path(match.group("path"))
                if source_path is None:
                    continue
                if source_path in EXPECTED_PRIVATE_PATHS:
                    continue
                if not (root / source_path).exists():
                    problems.append(
                        Problem(
                            path,
                            line_number,
                            f"referenced repository path does not exist: {source_path}",
                        )
                    )

        if fence is not None:
            problems.append(Problem(path, fence[1], "unclosed Markdown code fence"))

    return sorted(problems, key=lambda item: (str(item.path), item.line, item.message))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (defaults to the parent of scripts/)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    problems = check_documentation(args.root)
    for problem in problems:
        print(problem.render(args.root))
    if problems:
        print(f"Documentation check failed with {len(problems)} problem(s).")
        return 1
    print("Documentation check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

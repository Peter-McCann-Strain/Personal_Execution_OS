"""Audit a candidate public repository without printing detected values.

This scanner complements, rather than replaces, dedicated secret scanners such
as Gitleaks. Findings contain only a category and source location. Optional
private deny terms and values from a source ``.env`` are read in memory and are
never echoed.

Examples:

    python scripts/public_release_audit.py --root .
    python scripts/public_release_audit.py --root . --tracked-only --git-metadata
    python scripts/public_release_audit.py --root . \
        --deny-file /private/release-deny.txt \
        --source-env /private/source.env
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

_SKIP_DIRECTORIES = frozenset(
    {
        ".git",
        ".hypothesis",
        ".mypy_cache",
        ".playwright-mcp",
        ".pytest_cache",
        ".ruff_cache",
        ".serena",
        ".turbo",
        ".venv",
        "__pycache__",
        "build",
        "coverage",
        "dist",
        "htmlcov",
        "node_modules",
        "playwright-report",
        "test-results",
        "venv",
    }
)

_FORBIDDEN_FILENAMES = frozenset(
    {
        ".DS_Store",
        ".env",
        ".mcp.json",
        "credentials.json",
        "token.json",
    }
)

_FORBIDDEN_SUFFIXES = frozenset(
    {
        ".aab",
        ".apk",
        ".db",
        ".gif",
        ".gz",
        ".ipa",
        ".jar",
        ".jpeg",
        ".jpg",
        ".key",
        ".log",
        ".mov",
        ".mp4",
        ".p12",
        ".pdf",
        ".pem",
        ".pfx",
        ".png",
        ".sqlite",
        ".sqlite3",
        ".tar",
        ".tgz",
        ".webm",
        ".webp",
        ".zip",
    }
)

_ALLOWED_BINARY_PATHS = frozenset(
    {
        "docs/assets/product-mobile.png",
        "docs/assets/product-overview.png",
        "frontend/public/icon-192.png",
        "frontend/public/icon-512.png",
        "frontend/public/icon-maskable-192.png",
        "frontend/public/icon-maskable-512.png",
    }
)

_REVIEWED_BINARY_SHA256 = {
    # Fictional E2E data only; update after visually reviewing any replacement.
    "docs/assets/product-mobile.png": (
        "31bfc0827c400c0e1c1ba1d4a2b2203e4ae39649e198cfa56790172779a6adb5"
    ),
    "docs/assets/product-overview.png": (
        "8970ea96ddab41061cc6599701a674351d9acf3948c800a1207f9dd3413190c4"
    ),
}

_FORBIDDEN_PATH_PARTS = frozenset(
    {
        ".claude",
        ".playwright-mcp",
        "archive",
        "backups",
        "docker/data",
        "exports",
        "logs",
        "mcp_oauth",
        "mcp_trust",
        "screenshots",
    }
)

_GENERATED_LOCKFILES = frozenset({"package-lock.json", "pnpm-lock.yaml", "uv.lock"})

_ALLOWED_EMAIL_DOMAINS = frozenset(
    {
        "example.com",
        "example.net",
        "example.org",
        "users.noreply.github.com",
    }
)

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
_HOME_PATH_RE = re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+")
_PHONE_RE = re.compile(r"(?<!\w)\+[1-9](?:[\s().-]*\d){7,14}(?!\w)")
_IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
_ALLOWED_PUBLIC_TEST_IPS = frozenset(
    {
        # Historical example.com address used only to exercise the SSRF
        # validator's public-address path without contacting the network.
        "93.184.216.34",
    }
)

_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("telegram_token", re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b")),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    ),
    (
        "private_key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    (
        "sentry_dsn_with_credential",
        re.compile(r"https://[A-Za-z0-9]+@[A-Za-z0-9.-]+\.ingest\.[A-Za-z.]+/\d+"),
    ),
    (
        "live_supabase_project",
        re.compile(r"https://[a-z]{20}\.supabase\.co\b", re.IGNORECASE),
    ),
)

_SENSITIVE_ENV_KEY_RE = re.compile(
    r"(?:KEY|TOKEN|SECRET|PASSWORD|PASS|DSN|SID|URL|URI|PHONE|USER_ID|"
    r"ALLOWED_USER|DOMAIN|HOST|EMAIL|REPOSITORY)",
    re.IGNORECASE,
)

_SAFE_ENV_VALUES = frozenset(
    {
        "development",
        "false",
        "info",
        "localhost",
        "test",
        "true",
        "warning",
    }
)

_GIT_EXECUTABLE = shutil.which("git")


@dataclass(frozen=True, order=True)
class Finding:
    category: str
    path: str
    line: int | None = None
    context: str | None = None


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def _is_probably_binary(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return b"\x00" in handle.read(8192)
    except OSError:
        return True


def _iter_files(root: Path, *, tracked_only: bool) -> Iterable[Path]:
    if tracked_only:
        if _GIT_EXECUTABLE is None:
            raise SystemExit("--tracked-only requires Git")
        completed = subprocess.run(
            [_GIT_EXECUTABLE, "-C", str(root), "ls-files", "-z"],
            check=False,
            capture_output=True,
        )
        if completed.returncode != 0:
            raise SystemExit("--tracked-only requires a Git worktree")
        for raw in completed.stdout.split(b"\x00"):
            if raw:
                yield root / raw.decode("utf-8", errors="surrogateescape")
        return

    for path in root.rglob("*"):
        if any(part in _SKIP_DIRECTORIES for part in path.parts):
            continue
        if path.is_file() or path.is_symlink():
            yield path


def _path_findings(path: Path, root: Path) -> list[Finding]:
    relative = _relative(path, root)
    lowered_parts = tuple(part.lower() for part in Path(relative).parts)
    findings: list[Finding] = []

    if path.is_symlink():
        findings.append(Finding("symlink_not_allowed", relative))
        return findings

    if path.name in _FORBIDDEN_FILENAMES:
        findings.append(Finding("forbidden_filename", relative))
    elif path.name.startswith(".env") and path.name != ".env.example":
        findings.append(Finding("environment_file", relative))

    if path.suffix.lower() in _FORBIDDEN_SUFFIXES:
        if relative not in _ALLOWED_BINARY_PATHS:
            findings.append(Finding("forbidden_binary_or_archive", relative))
        elif (expected_digest := _REVIEWED_BINARY_SHA256.get(relative)) and hashlib.sha256(
            path.read_bytes()
        ).hexdigest() != expected_digest:
            findings.append(Finding("unreviewed_binary_changed", relative))

    for part in _FORBIDDEN_PATH_PARTS:
        candidate_parts = tuple(part.split("/"))
        width = len(candidate_parts)
        if any(
            lowered_parts[index : index + width] == candidate_parts
            for index in range(len(lowered_parts) - width + 1)
        ):
            findings.append(Finding("forbidden_runtime_path", relative))
            break

    return findings


def _allowed_phone(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    if digits.startswith("120255501") and len(digits) == 11:
        return True
    # Ofcom drama-use ranges. These are reserved for fictional examples:
    # London 020 7946 0000-0999 and mobile 07700 900000-900999.
    if len(digits) == 12 and digits.startswith("44207946"):
        return 0 <= int(digits[-4:]) <= 999
    if len(digits) == 12 and digits.startswith("447700900"):
        return 0 <= int(digits[-3:]) <= 999
    return False


def _allowed_ip(value: str) -> bool:
    if value in _ALLOWED_PUBLIC_TEST_IPS:
        return True
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    documentation_ranges = (
        ipaddress.ip_network("192.0.2.0/24"),
        ipaddress.ip_network("198.51.100.0/24"),
        ipaddress.ip_network("203.0.113.0/24"),
    )
    return not address.is_global or any(address in network for network in documentation_ranges)


def _line_findings(text: str, relative: str) -> list[Finding]:
    findings: list[Finding] = []
    generated_lockfile = Path(relative).name in _GENERATED_LOCKFILES
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not generated_lockfile:
            for match in _EMAIL_RE.finditer(line):
                domain = match.group(1).lower()
                if domain not in _ALLOWED_EMAIL_DOMAINS and not domain.endswith(".invalid"):
                    findings.append(Finding("non_example_email", relative, line_number))

        if _HOME_PATH_RE.search(line):
            findings.append(Finding("absolute_home_path", relative, line_number))

        if not generated_lockfile:
            for match in _PHONE_RE.finditer(line):
                if not _allowed_phone(match.group(0)):
                    findings.append(Finding("non_example_phone", relative, line_number))

        for match in _IPV4_RE.finditer(line):
            if not _allowed_ip(match.group(0)):
                findings.append(Finding("public_ip_address", relative, line_number))

        for category, pattern in _SECRET_PATTERNS:
            if pattern.search(line):
                findings.append(Finding(category, relative, line_number))

    return findings


def _read_deny_terms(path: Path | None) -> list[str]:
    if path is None:
        return []
    terms: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        term = line.strip()
        if term and not term.startswith("#"):
            terms.append(term)
    return terms


def _parse_source_env(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if (
            _SENSITIVE_ENV_KEY_RE.search(key)
            and len(value) >= 6
            and value.lower() not in _SAFE_ENV_VALUES
            and "localhost" not in value.lower()
            and "example." not in value.lower()
        ):
            values[key] = value
    return values


def _private_value_findings(
    text: str,
    relative: str,
    *,
    deny_terms: list[str],
    source_values: dict[str, str],
) -> list[Finding]:
    findings: list[Finding] = []
    folded = text.casefold()

    for index, term in enumerate(deny_terms, start=1):
        if term.casefold() in folded:
            findings.append(Finding("private_deny_term", relative, context=f"term_{index}"))

    for key, value in source_values.items():
        if value in text:
            findings.append(Finding("private_source_value", relative, context=f"env:{key}"))

    return findings


def _git_metadata_findings(root: Path, deny_terms: list[str]) -> list[Finding]:
    if _GIT_EXECUTABLE is None:
        return [Finding("git_metadata_unavailable", ".git")]
    completed = subprocess.run(
        [
            _GIT_EXECUTABLE,
            "-C",
            str(root),
            "log",
            "HEAD",
            "--format=%H%x00%an%x00%ae%x00%cn%x00%ce",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return [Finding("git_metadata_unavailable", ".git")]

    findings: list[Finding] = []
    for row in completed.stdout.splitlines():
        fields = row.split("\x00")
        if len(fields) != 5:
            continue
        commit, author_name, author_email, committer_name, committer_email = fields
        short_commit = commit[:12]

        for email in (author_email, committer_email):
            match = _EMAIL_RE.fullmatch(email)
            if match and match.group(1).lower() not in _ALLOWED_EMAIL_DOMAINS:
                findings.append(Finding("git_non_private_email", ".git", context=short_commit))
                break

        identity = f"{author_name}\n{committer_name}".casefold()
        for index, term in enumerate(deny_terms, start=1):
            if term.casefold() in identity:
                findings.append(
                    Finding(
                        "git_private_deny_term",
                        ".git",
                        context=f"{short_commit}:term_{index}",
                    )
                )
                break

    return findings


def audit(
    *,
    root: Path,
    tracked_only: bool,
    deny_file: Path | None,
    source_env: Path | None,
    git_metadata: bool,
) -> list[Finding]:
    root = root.resolve()
    deny_terms = _read_deny_terms(deny_file)
    source_values = _parse_source_env(source_env)
    findings: list[Finding] = []

    for path in _iter_files(root, tracked_only=tracked_only):
        findings.extend(_path_findings(path, root))
        if path.is_symlink() or _is_probably_binary(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            findings.append(Finding("unreadable_file", _relative(path, root)))
            continue
        relative = _relative(path, root)
        findings.extend(_line_findings(text, relative))
        findings.extend(
            _private_value_findings(
                text,
                relative,
                deny_terms=deny_terms,
                source_values=source_values,
            )
        )

    if git_metadata:
        findings.extend(_git_metadata_findings(root, deny_terms))

    return sorted(set(findings))


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit a public-release tree without printing detected values."
    )
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--tracked-only",
        action="store_true",
        help="Scan only files returned by git ls-files.",
    )
    parser.add_argument(
        "--deny-file",
        type=Path,
        help="Private newline-delimited deny terms; values are never printed.",
    )
    parser.add_argument(
        "--source-env",
        type=Path,
        help="Private source env whose sensitive values must not appear in the tree.",
    )
    parser.add_argument(
        "--git-metadata",
        action="store_true",
        help="Audit author and committer metadata in revisions reachable from HEAD.",
    )
    parser.add_argument("--json", action="store_true", help="Emit redacted JSON.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    findings = audit(
        root=args.root,
        tracked_only=args.tracked_only,
        deny_file=args.deny_file,
        source_env=args.source_env,
        git_metadata=args.git_metadata,
    )

    if args.json:
        print(
            json.dumps(
                {
                    "finding_count": len(findings),
                    "findings": [asdict(finding) for finding in findings],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        for finding in findings:
            location = finding.path
            if finding.line is not None:
                location = f"{location}:{finding.line}"
            suffix = f" ({finding.context})" if finding.context else ""
            print(f"[{finding.category}] {location}{suffix}")
        print(f"Public release audit: {len(findings)} finding(s).")

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())

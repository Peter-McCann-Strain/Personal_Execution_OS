from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.public_release_audit import _git_metadata_findings


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _commit(repo: Path, *, message: str, email: str, content: str) -> None:
    _git(repo, "config", "user.name", "Release Test")
    _git(repo, "config", "user.email", email)
    (repo / "release.txt").write_text(content, encoding="utf-8")
    _git(repo, "add", "release.txt")
    _git(repo, "commit", "-m", message)


def test_git_metadata_audit_follows_only_head_ancestry(tmp_path: Path) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    _commit(
        tmp_path,
        message="Release commit",
        email="maintainers@users.noreply.github.com",
        content="release\n",
    )

    _git(tmp_path, "switch", "-c", "automation-update")
    _commit(
        tmp_path,
        message="Unmerged automation commit",
        email="automation@updates.invalid",
        content="automation\n",
    )
    _git(tmp_path, "switch", "main")

    assert _git_metadata_findings(tmp_path, []) == []


def test_git_metadata_audit_reports_email_in_head_ancestry(tmp_path: Path) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    _commit(
        tmp_path,
        message="Release commit",
        email="person@company.invalid",
        content="release\n",
    )

    findings = _git_metadata_findings(tmp_path, [])

    assert [finding.category for finding in findings] == ["git_non_private_email"]

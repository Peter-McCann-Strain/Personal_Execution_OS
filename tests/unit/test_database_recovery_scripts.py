"""Adversarial checks for database backup integrity validation."""

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RESTORE_SCRIPT = ROOT / "scripts" / "restore-database.sh"


def _archive_with_fake_docker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    content: bytes = b"valid pg_dump fixture",
) -> tuple[Path, Path]:
    archive = tmp_path / "requested.dump"
    archive.write_bytes(content)

    invoked = tmp_path / "docker-invoked"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        '#!/bin/sh\nprintf "invoked\\n" >"$DOCKER_SENTINEL"\nexit 1\n',
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)

    monkeypatch.setenv("DOCKER_SENTINEL", str(invoked))
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ['PATH']}")
    return archive, invoked


def _restore(archive: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "sh",
            str(RESTORE_SCRIPT),
            str(archive),
            "--confirm-destroy-local-data",
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def test_restore_binds_checksum_sidecar_to_requested_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b"archive selected by the operator"
    archive, docker_invoked = _archive_with_fake_docker(tmp_path, monkeypatch, content)
    archive.with_suffix(".dump.sha256").write_text(
        f"{_digest(content)}  different.dump\n",
        encoding="utf-8",
    )

    completed = _restore(archive)

    assert completed.returncode == 1
    assert "must name the requested archive: requested.dump" in completed.stderr
    assert not docker_invoked.exists()


@pytest.mark.parametrize(
    ("sidecar", "expected_error"),
    [
        ("not-a-sha256  requested.dump\n", "invalid SHA-256 digest"),
        (
            "{digest} requested.dump\n",
            "must use two spaces before the backup filename",
        ),
        (
            "{digest}  requested.dump\n{digest}  other.dump\n",
            "must contain exactly one record",
        ),
    ],
    ids=["malformed-digest", "malformed-separator", "multiple-records"],
)
def test_restore_rejects_malformed_or_multiline_checksum_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sidecar: str,
    expected_error: str,
) -> None:
    content = b"archive with malformed sidecar"
    archive, docker_invoked = _archive_with_fake_docker(tmp_path, monkeypatch, content)
    archive.with_suffix(".dump.sha256").write_text(
        sidecar.format(digest=_digest(content)),
        encoding="utf-8",
    )

    completed = _restore(archive)

    assert completed.returncode == 1
    assert expected_error in completed.stderr
    assert not docker_invoked.exists()


def test_restore_hashes_requested_archive_instead_of_trusting_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = b"original archive"
    archive, docker_invoked = _archive_with_fake_docker(tmp_path, monkeypatch, original)
    archive.with_suffix(".dump.sha256").write_text(
        f"{_digest(original)}  requested.dump\n",
        encoding="utf-8",
    )
    archive.write_bytes(b"tampered archive")

    completed = _restore(archive)

    assert completed.returncode == 1
    assert "checksum does not match the requested archive" in completed.stderr
    assert not docker_invoked.exists()


def test_restore_accepts_backup_script_checksum_format(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b"untampered archive"
    archive, docker_invoked = _archive_with_fake_docker(tmp_path, monkeypatch, content)
    archive.with_suffix(".dump.sha256").write_text(
        f"{_digest(content)}  requested.dump\n",
        encoding="utf-8",
    )

    completed = _restore(archive)

    assert completed.returncode == 1
    assert "Docker with Compose v2 is required." in completed.stderr
    assert docker_invoked.exists()

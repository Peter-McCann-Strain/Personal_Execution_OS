"""Adversarial checks for database backup integrity validation."""

import hashlib
import os
import shutil
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
    assert "Docker with the Compose plugin is required." in completed.stderr
    assert docker_invoked.exists()


def _failure_injection_project(
    tmp_path: Path,
    *,
    fail_migrations: str,
) -> tuple[Path, Path, dict[str, str]]:
    project = tmp_path / "project"
    scripts = project / "scripts"
    backups = project / "backups"
    fake_bin = tmp_path / "bin"
    scripts.mkdir(parents=True)
    backups.mkdir()
    fake_bin.mkdir()
    for script_name in ("backup-database.sh", "restore-database.sh"):
        shutil.copy2(ROOT / "scripts" / script_name, scripts / script_name)

    requested = backups / "requested.dump"
    requested.write_bytes(b"requested database archive")
    requested.with_suffix(".dump.sha256").write_text(
        f"{_digest(requested.read_bytes())}  {requested.name}\n",
        encoding="utf-8",
    )

    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        """#!/bin/sh
set -eu

printf '%s\\n' "$*" >>"$FAKE_DOCKER_LOG"
[ "${1:-}" = "compose" ] || exit 64
shift

case "${1:-}" in
    version | stop | up)
        exit 0
        ;;
    run)
        shift
        [ "${1:-}" = "--rm" ] && shift
        [ "${1:-}" = "migrate" ] || exit 65
        case "${FAKE_FAIL_MIGRATIONS:-}" in
            always)
                exit 66
                ;;
            once)
                if [ ! -e "$FAKE_MIGRATION_MARKER" ]; then
                    : >"$FAKE_MIGRATION_MARKER"
                    exit 66
                fi
                ;;
        esac
        exit 0
        ;;
    exec)
        shift
        [ "${1:-}" = "-T" ] && shift
        [ "${1:-}" = "postgres" ] || exit 67
        shift
        case "${1:-}" in
            pg_dump)
                printf '%s' "verified safety database archive"
                ;;
            pg_restore | dropdb | createdb | psql)
                exit 0
                ;;
            *)
                exit 68
                ;;
        esac
        ;;
    *)
        exit 69
        ;;
esac
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "FAKE_DOCKER_LOG": str(tmp_path / "docker.log"),
            "FAKE_FAIL_MIGRATIONS": fail_migrations,
            "FAKE_MIGRATION_MARKER": str(tmp_path / "migration-failed-once"),
        }
    )
    return project, requested, env


def _run_failure_injection_restore(
    project: Path,
    requested: Path,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "sh",
            str(project / "scripts" / "restore-database.sh"),
            str(requested),
            "--confirm-destroy-local-data",
        ],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )


def test_failed_post_restore_migration_rolls_back_verified_database(
    tmp_path: Path,
) -> None:
    project, requested, env = _failure_injection_project(
        tmp_path,
        fail_migrations="once",
    )

    completed = _run_failure_injection_restore(project, requested, env)

    assert completed.returncode == 1
    assert "Restore workflow failed. Attempting automatic rollback" in completed.stderr
    assert "Rollback succeeded; the requested backup was not installed." in completed.stderr
    safety_backups = list((project / "backups").glob("pre-restore-*.dump"))
    assert len(safety_backups) == 1
    assert safety_backups[0].read_bytes() == b"verified safety database archive"
    assert Path(f"{safety_backups[0]}.sha256").is_file()
    docker_log = Path(env["FAKE_DOCKER_LOG"]).read_text(encoding="utf-8")
    assert docker_log.count("compose run --rm migrate") == 2
    assert "compose up --detach --wait" in docker_log


def test_failed_database_rollback_leaves_services_stopped_with_safety_backup(
    tmp_path: Path,
) -> None:
    project, requested, env = _failure_injection_project(
        tmp_path,
        fail_migrations="always",
    )

    completed = _run_failure_injection_restore(project, requested, env)

    assert completed.returncode == 1
    assert "Automatic rollback failed. Services remain stopped." in completed.stderr
    safety_backups = list((project / "backups").glob("pre-restore-*.dump"))
    assert len(safety_backups) == 1
    assert safety_backups[0].read_bytes() == b"verified safety database archive"
    assert Path(f"{safety_backups[0]}.sha256").is_file()
    docker_log = Path(env["FAKE_DOCKER_LOG"]).read_text(encoding="utf-8")
    assert docker_log.count("compose run --rm migrate") == 2
    assert "compose up --detach --wait" not in docker_log

"""Adversarial tests for the versioned local-state backup and restore helpers."""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import stat
import subprocess
import tarfile
from copy import copy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_NAMES = (
    "backup-local-state.sh",
    "restore-local-state.sh",
    "local-state-archive-common.sh",
)
ARCHIVE_ROOT = "personal-execution-os-local-state-v1"


def _fake_project(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    project = tmp_path / "project"
    scripts = project / "scripts"
    config = project / "config"
    fake_bin = tmp_path / "bin"
    volume_root = tmp_path / "volumes"
    scripts.mkdir(parents=True)
    config.mkdir()
    fake_bin.mkdir()
    volume_root.mkdir()

    for script_name in SCRIPT_NAMES:
        shutil.copy2(ROOT / "scripts" / script_name, scripts / script_name)

    (project / ".env").write_text(
        "POSTGRES_PASSWORD=database-secret\nCONNECTOR_TOKEN_ENCRYPTION_KEY=connector-secret\n",
        encoding="utf-8",
    )
    (config / "IDENTITY.local.md").write_text(
        "# Local identity\n\nPrivate preferences.\n",
        encoding="utf-8",
    )

    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        """#!/bin/sh
set -eu

if [ -n "${FAKE_DOCKER_LOG:-}" ]; then
    printf '%s\\n' "$*" >>"$FAKE_DOCKER_LOG"
fi

command_name=${1:-}
shift || true
case "$command_name" in
    version)
        exit 0
        ;;
    ps)
        if [ -n "${FAKE_RUNNING_CONTAINERS:-}" ]; then
            printf '%s\\n' "$FAKE_RUNNING_CONTAINERS"
        fi
        exit 0
        ;;
    image)
        exit 0
        ;;
    pull)
        exit 0
        ;;
    volume)
        volume_command=${1:-}
        shift || true
        case "$volume_command" in
            inspect)
                [ -d "$FAKE_VOLUME_ROOT/$1" ]
                ;;
            create)
                volume_name=""
                while [ "$#" -gt 0 ]; do
                    case "$1" in
                        --label)
                            shift 2
                            ;;
                        *)
                            volume_name=$1
                            shift
                            ;;
                    esac
                done
                mkdir -p "$FAKE_VOLUME_ROOT/$volume_name"
                printf '%s\\n' "$volume_name"
                ;;
            rm)
                rm -rf -- "$FAKE_VOLUME_ROOT/$1"
                ;;
            *)
                exit 64
                ;;
        esac
        ;;
    run)
        volume_spec=""
        entrypoint=""
        while [ "$#" -gt 0 ]; do
            case "$1" in
                --rm | --read-only)
                    shift
                    ;;
                --network | --user | --volume | --entrypoint)
                    option=$1
                    value=$2
                    shift 2
                    case "$option" in
                        --volume) volume_spec=$value ;;
                        --entrypoint) entrypoint=$value ;;
                    esac
                    ;;
                *)
                    shift
                    break
                    ;;
            esac
        done
        volume_name=${volume_spec%%:*}
        target=${volume_spec#*:}
        volume_dir="$FAKE_VOLUME_ROOT/$volume_name"
        mkdir -p "$volume_dir"
        case "$target:$entrypoint" in
            /archive-source:ro:tar)
                tar -C "$volume_dir" -cf - .
                ;;
            /restore-target:tar)
                tar -C "$volume_dir" -xf -
                ;;
            /restore-target:sh)
                if [ "${FAKE_FAIL_VOLUME_REPLACE_ALWAYS:-}" = "1" ]; then
                    exit 66
                fi
                if [ -n "${FAKE_FAIL_VOLUME_REPLACE_ONCE_MARKER:-}" ] &&
                    [ ! -e "$FAKE_FAIL_VOLUME_REPLACE_ONCE_MARKER" ]; then
                    : >"$FAKE_FAIL_VOLUME_REPLACE_ONCE_MARKER"
                    exit 66
                fi
                find "$volume_dir" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} \\;
                tar -C "$volume_dir" -xf -
                ;;
            *)
                printf 'unexpected fake docker run: %s %s\\n' "$target" "$entrypoint" >&2
                exit 65
                ;;
        esac
        ;;
    *)
        exit 64
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
            "FAKE_VOLUME_ROOT": str(volume_root),
            "FAKE_DOCKER_LOG": str(tmp_path / "docker.log"),
            "PEOS_APP_DATA_VOLUME": "test-app-data",
            "COMPOSE_PROJECT_NAME": "test-personal-execution-os",
        }
    )
    return project, volume_root, env


def _run(
    project: Path,
    script_name: str,
    *arguments: str,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(project / "scripts" / script_name), *arguments],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )


def _create_archive(
    tmp_path: Path,
) -> tuple[Path, Path, Path, dict[str, str]]:
    project, volume_root, env = _fake_project(tmp_path)
    app_data = volume_root / "test-app-data"
    (app_data / "evaluation" / "exports").mkdir(parents=True)
    (app_data / "evaluation" / "exports" / "result.json").write_text(
        '{"passing": true}\n',
        encoding="utf-8",
    )
    archive = project / "backups" / "local-state.tar.gz"
    completed = _run(
        project,
        "backup-local-state.sh",
        str(archive),
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    return project, volume_root, archive, env


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rewrite_outer_archive(archive: Path, replacements: dict[str, bytes]) -> None:
    rewritten = archive.with_name(f"{archive.name}.rewritten")
    with (
        tarfile.open(archive, "r:gz") as source,
        tarfile.open(
            rewritten,
            "w:gz",
        ) as destination,
    ):
        for source_member in source.getmembers():
            member = copy(source_member)
            if not source_member.isfile():
                destination.addfile(member)
                continue
            original = source.extractfile(source_member)
            assert original is not None
            payload = replacements.get(source_member.name, original.read())
            member.size = len(payload)
            destination.addfile(member, io.BytesIO(payload))
    rewritten.replace(archive)
    Path(f"{archive}.sha256").write_text(
        f"{_sha256(archive)}  {archive.name}\n",
        encoding="utf-8",
    )


def test_backup_creates_private_versioned_archive_with_two_integrity_layers(
    tmp_path: Path,
) -> None:
    project, _, archive, _ = _create_archive(tmp_path)
    sidecar = Path(f"{archive}.sha256")

    assert stat.S_IMODE(archive.stat().st_mode) == 0o600
    assert stat.S_IMODE(sidecar.stat().st_mode) == 0o600
    assert sidecar.read_text(encoding="utf-8") == f"{_sha256(archive)}  {archive.name}\n"

    with tarfile.open(archive, "r:gz") as outer:
        assert outer.getnames()[0] == ARCHIVE_ROOT
        assert set(outer.getnames()) == {
            ARCHIVE_ROOT,
            f"{ARCHIVE_ROOT}/FORMAT",
            f"{ARCHIVE_ROOT}/METADATA",
            f"{ARCHIVE_ROOT}/config.env",
            f"{ARCHIVE_ROOT}/IDENTITY.local.md",
            f"{ARCHIVE_ROOT}/app-data.tar",
            f"{ARCHIVE_ROOT}/MANIFEST.sha256",
        }
        format_bytes = outer.extractfile(f"{ARCHIVE_ROOT}/FORMAT").read()
        metadata_bytes = outer.extractfile(f"{ARCHIVE_ROOT}/METADATA").read()
        app_data_bytes = outer.extractfile(f"{ARCHIVE_ROOT}/app-data.tar").read()
        env_bytes = outer.extractfile(f"{ARCHIVE_ROOT}/config.env").read()
        identity_bytes = outer.extractfile(f"{ARCHIVE_ROOT}/IDENTITY.local.md").read()
        manifest = outer.extractfile(f"{ARCHIVE_ROOT}/MANIFEST.sha256").read().decode()

    assert format_bytes == b"personal-execution-os-local-state\nversion=1\n"
    assert b"includes=app-data,.env,config/IDENTITY.local.md\n" in metadata_bytes
    assert b"excludes=postgresql,redis\n" in metadata_bytes
    assert env_bytes == (project / ".env").read_bytes()
    assert identity_bytes == (project / "config" / "IDENTITY.local.md").read_bytes()

    expected_manifest = "".join(
        f"{hashlib.sha256(content).hexdigest()}  {name}\n"
        for name, content in (
            ("FORMAT", format_bytes),
            ("METADATA", metadata_bytes),
            ("app-data.tar", app_data_bytes),
            ("config.env", env_bytes),
            ("IDENTITY.local.md", identity_bytes),
        )
    )
    assert manifest == expected_manifest

    with tarfile.open(fileobj=io.BytesIO(app_data_bytes), mode="r:") as app_data:
        assert "./evaluation/exports/result.json" in app_data.getnames()
        assert (
            app_data.extractfile("./evaluation/exports/result.json").read()
            == b'{"passing": true}\n'
        )


def test_backup_refuses_running_services_and_existing_output(
    tmp_path: Path,
) -> None:
    project, volume_root, env = _fake_project(tmp_path)
    (volume_root / "test-app-data").mkdir()
    archive = project / "backups" / "local-state.tar.gz"

    running_env = env | {"FAKE_RUNNING_CONTAINERS": "test-api-1\ntest-worker-1"}
    running = _run(
        project,
        "backup-local-state.sh",
        str(archive),
        env=running_env,
    )
    assert running.returncode == 1
    assert "services are running" in running.stderr
    assert not archive.exists()

    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(b"keep this archive")
    existing = _run(
        project,
        "backup-local-state.sh",
        str(archive),
        env=env,
    )
    assert existing.returncode == 1
    assert "Refusing to overwrite existing local-state backup" in existing.stderr
    assert archive.read_bytes() == b"keep this archive"


def test_backup_refuses_linked_private_configuration(tmp_path: Path) -> None:
    project, volume_root, env = _fake_project(tmp_path)
    (volume_root / "test-app-data").mkdir()
    outside = tmp_path / "outside.env"
    outside.write_text("SECRET=outside\n", encoding="utf-8")
    (project / ".env").unlink()
    (project / ".env").symlink_to(outside)

    completed = _run(
        project,
        "backup-local-state.sh",
        str(project / "backup.tar.gz"),
        env=env,
    )

    assert completed.returncode == 1
    assert ".env must be an existing regular file, not a link" in completed.stderr


def test_restore_replaces_all_supported_state_and_preserves_private_permissions(
    tmp_path: Path,
) -> None:
    project, volume_root, archive, env = _create_archive(tmp_path)
    app_data = volume_root / "test-app-data"
    (project / ".env").write_text("CHANGED=true\n", encoding="utf-8")
    (project / "config" / "IDENTITY.local.md").write_text(
        "# Changed identity\n",
        encoding="utf-8",
    )
    shutil.rmtree(app_data / "evaluation")
    (app_data / "stale.txt").write_text("must disappear\n", encoding="utf-8")

    completed = _run(
        project,
        "restore-local-state.sh",
        str(archive),
        "--confirm-replace-local-state",
        env=env,
    )

    assert completed.returncode == 0, completed.stderr
    assert "PostgreSQL and Redis were not changed" in completed.stdout
    assert (
        (project / ".env")
        .read_text(encoding="utf-8")
        .startswith("POSTGRES_PASSWORD=database-secret")
    )
    assert "Private preferences." in (project / "config" / "IDENTITY.local.md").read_text(
        encoding="utf-8"
    )
    assert stat.S_IMODE((project / ".env").stat().st_mode) == 0o600
    assert stat.S_IMODE((project / "config" / "IDENTITY.local.md").stat().st_mode) == 0o600
    assert not (app_data / "stale.txt").exists()
    assert (app_data / "evaluation" / "exports" / "result.json").exists()
    assert list((project / "backups").glob("pre-local-state-restore-*.tar.gz"))


def test_restore_requires_confirmation_and_stopped_services(tmp_path: Path) -> None:
    project, volume_root, archive, env = _create_archive(tmp_path)
    marker = volume_root / "test-app-data" / "do-not-change.txt"
    marker.write_text("live\n", encoding="utf-8")

    missing_confirmation = _run(
        project,
        "restore-local-state.sh",
        str(archive),
        env=env,
    )
    assert missing_confirmation.returncode == 2
    assert "--confirm-replace-local-state" in missing_confirmation.stderr

    running_env = env | {"FAKE_RUNNING_CONTAINERS": "test-api-1"}
    running = _run(
        project,
        "restore-local-state.sh",
        str(archive),
        "--confirm-replace-local-state",
        env=running_env,
    )
    assert running.returncode == 1
    assert "services are running" in running.stderr
    assert marker.read_text(encoding="utf-8") == "live\n"


def test_restore_rejects_tampering_before_invoking_docker(tmp_path: Path) -> None:
    project, volume_root, archive, env = _create_archive(tmp_path)
    docker_log = Path(env["FAKE_DOCKER_LOG"])
    docker_log.unlink()
    archive.write_bytes(archive.read_bytes() + b"tampered")
    marker = volume_root / "test-app-data" / "do-not-change.txt"
    marker.write_text("live\n", encoding="utf-8")

    completed = _run(
        project,
        "restore-local-state.sh",
        str(archive),
        "--confirm-replace-local-state",
        env=env,
    )

    assert completed.returncode == 1
    assert "checksum does not match" in completed.stderr
    assert not docker_log.exists()
    assert marker.read_text(encoding="utf-8") == "live\n"


def test_restore_binds_outer_checksum_to_selected_archive_name(tmp_path: Path) -> None:
    project, _, archive, env = _create_archive(tmp_path)
    Path(f"{archive}.sha256").write_text(
        f"{_sha256(archive)}  substituted.tar.gz\n",
        encoding="utf-8",
    )
    docker_log = Path(env["FAKE_DOCKER_LOG"])
    docker_log.unlink()

    completed = _run(
        project,
        "restore-local-state.sh",
        str(archive),
        "--confirm-replace-local-state",
        env=env,
    )

    assert completed.returncode == 1
    assert "must name the requested archive" in completed.stderr
    assert not docker_log.exists()


def test_restore_verifies_internal_manifest_after_outer_checksum(
    tmp_path: Path,
) -> None:
    project, _, archive, env = _create_archive(tmp_path)
    _rewrite_outer_archive(
        archive,
        {f"{ARCHIVE_ROOT}/config.env": b"ATTACKER_REPLACED=true\n"},
    )
    docker_log = Path(env["FAKE_DOCKER_LOG"])
    docker_log.unlink()

    completed = _run(
        project,
        "restore-local-state.sh",
        str(archive),
        "--confirm-replace-local-state",
        env=env,
    )

    assert completed.returncode == 1
    assert "integrity check failed for config.env" in completed.stderr
    assert not docker_log.exists()


def test_restore_rejects_inner_volume_traversal_with_valid_integrity_hashes(
    tmp_path: Path,
) -> None:
    project, _, archive, env = _create_archive(tmp_path)
    malicious_inner = io.BytesIO()
    with tarfile.open(fileobj=malicious_inner, mode="w:") as inner:
        root = tarfile.TarInfo("./")
        root.type = tarfile.DIRTYPE
        root.mode = 0o700
        inner.addfile(root)
        payload = b"escape"
        traversal = tarfile.TarInfo("./../escaped")
        traversal.size = len(payload)
        traversal.mode = 0o600
        inner.addfile(traversal, io.BytesIO(payload))
    malicious_bytes = malicious_inner.getvalue()

    with tarfile.open(archive, "r:gz") as outer:
        manifest_file = outer.extractfile(f"{ARCHIVE_ROOT}/MANIFEST.sha256")
        assert manifest_file is not None
        manifest_lines = manifest_file.read().decode().splitlines()
    manifest_lines[2] = f"{hashlib.sha256(malicious_bytes).hexdigest()}  app-data.tar"
    _rewrite_outer_archive(
        archive,
        {
            f"{ARCHIVE_ROOT}/app-data.tar": malicious_bytes,
            f"{ARCHIVE_ROOT}/MANIFEST.sha256": ("\n".join(manifest_lines) + "\n").encode(),
        },
    )
    docker_log = Path(env["FAKE_DOCKER_LOG"])
    docker_log.unlink()

    completed = _run(
        project,
        "restore-local-state.sh",
        str(archive),
        "--confirm-replace-local-state",
        env=env,
    )

    assert completed.returncode == 1
    assert "unsafe, duplicate, or non-relative path" in completed.stderr
    assert not (tmp_path / "escaped").exists()
    assert not docker_log.exists()


def test_restore_rejects_traversal_member_before_invoking_docker(
    tmp_path: Path,
) -> None:
    project, volume_root, _, env = _create_archive(tmp_path)
    malicious = project / "backups" / "traversal.tar.gz"
    with tarfile.open(malicious, "w:gz") as outer:
        root = tarfile.TarInfo(ARCHIVE_ROOT)
        root.type = tarfile.DIRTYPE
        root.mode = 0o700
        outer.addfile(root)
        payload = b"escape"
        traversal = tarfile.TarInfo("../../escaped")
        traversal.size = len(payload)
        traversal.mode = 0o600
        outer.addfile(traversal, io.BytesIO(payload))
    Path(f"{malicious}.sha256").write_text(
        f"{_sha256(malicious)}  {malicious.name}\n",
        encoding="utf-8",
    )
    docker_log = Path(env["FAKE_DOCKER_LOG"])
    docker_log.unlink()
    marker = volume_root / "test-app-data" / "do-not-change.txt"
    marker.write_text("live\n", encoding="utf-8")

    completed = _run(
        project,
        "restore-local-state.sh",
        str(malicious),
        "--confirm-replace-local-state",
        env=env,
    )

    assert completed.returncode == 1
    assert "unexpected, missing, or duplicate members" in completed.stderr
    assert not (tmp_path / "escaped").exists()
    assert not docker_log.exists()
    assert marker.read_text(encoding="utf-8") == "live\n"


def test_restore_refuses_ambiguous_partial_existing_state(tmp_path: Path) -> None:
    project, volume_root, archive, env = _create_archive(tmp_path)
    shutil.rmtree(volume_root / "test-app-data")

    completed = _run(
        project,
        "restore-local-state.sh",
        str(archive),
        "--confirm-replace-local-state",
        env=env,
    )

    assert completed.returncode == 1
    assert "Refusing partial-state restore" in completed.stderr


def test_restore_rolls_back_existing_state_after_live_volume_failure(
    tmp_path: Path,
) -> None:
    project, volume_root, archive, env = _create_archive(tmp_path)
    app_data = volume_root / "test-app-data"
    (project / ".env").write_text("PREVIOUS_ENV=true\n", encoding="utf-8")
    (project / "config" / "IDENTITY.local.md").write_text(
        "# Previous identity\n",
        encoding="utf-8",
    )
    shutil.rmtree(app_data)
    app_data.mkdir()
    (app_data / "previous.txt").write_text("keep me\n", encoding="utf-8")
    fail_once_marker = tmp_path / "failed-volume-replace"

    completed = _run(
        project,
        "restore-local-state.sh",
        str(archive),
        "--confirm-replace-local-state",
        env=env | {"FAKE_FAIL_VOLUME_REPLACE_ONCE_MARKER": str(fail_once_marker)},
    )

    assert completed.returncode == 1
    assert "Local-state restore failed; attempting rollback." in completed.stderr
    assert "Rollback succeeded; requested local state was not installed." in completed.stderr
    assert (project / ".env").read_text(encoding="utf-8") == "PREVIOUS_ENV=true\n"
    assert (project / "config" / "IDENTITY.local.md").read_text(
        encoding="utf-8"
    ) == "# Previous identity\n"
    assert (app_data / "previous.txt").read_text(encoding="utf-8") == "keep me\n"
    assert not (app_data / "evaluation").exists()
    safety_archives = list((project / "backups").glob("pre-local-state-restore-*.tar.gz"))
    assert len(safety_archives) == 1
    assert Path(f"{safety_archives[0]}.sha256").is_file()


def test_restore_reports_verified_safety_archive_when_rollback_fails(
    tmp_path: Path,
) -> None:
    project, volume_root, archive, env = _create_archive(tmp_path)
    app_data = volume_root / "test-app-data"
    (project / ".env").write_text("PREVIOUS_ENV=true\n", encoding="utf-8")
    (project / "config" / "IDENTITY.local.md").write_text(
        "# Previous identity\n",
        encoding="utf-8",
    )
    shutil.rmtree(app_data)
    app_data.mkdir()
    (app_data / "previous.txt").write_text("keep me\n", encoding="utf-8")

    completed = _run(
        project,
        "restore-local-state.sh",
        str(archive),
        "--confirm-replace-local-state",
        env=env | {"FAKE_FAIL_VOLUME_REPLACE_ALWAYS": "1"},
    )

    assert completed.returncode == 1
    assert "Rollback failed. Services remain stopped." in completed.stderr
    safety_line = next(
        line
        for line in completed.stderr.splitlines()
        if line.startswith("Verified safety archive: ")
    )
    safety_archive = Path(safety_line.removeprefix("Verified safety archive: "))
    assert safety_archive.is_file()
    assert Path(f"{safety_archive}.sha256").is_file()
    assert (project / ".env").read_text(encoding="utf-8") == "PREVIOUS_ENV=true\n"
    assert (project / "config" / "IDENTITY.local.md").read_text(
        encoding="utf-8"
    ) == "# Previous identity\n"
    assert (app_data / "previous.txt").read_text(encoding="utf-8") == "keep me\n"

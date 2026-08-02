#!/bin/sh

set -eu
umask 077

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH='' cd -- "$SCRIPT_DIR/.." && pwd)
# shellcheck source=scripts/local-state-archive-common.sh
. "$SCRIPT_DIR/local-state-archive-common.sh"

stage_dir=""
rollback_stage=""
env_tmp=""
identity_tmp=""
verification_volume=""

cleanup() {
    if [ -n "$verification_volume" ]; then
        docker volume rm "$verification_volume" >/dev/null 2>&1 || true
    fi
    if [ -n "$stage_dir" ] && [ -d "$stage_dir" ]; then
        rm -rf -- "$stage_dir"
    fi
    if [ -n "$rollback_stage" ] && [ -d "$rollback_stage" ]; then
        rm -rf -- "$rollback_stage"
    fi
    if [ -n "$env_tmp" ] && [ -f "$env_tmp" ]; then
        rm -f -- "$env_tmp"
    fi
    if [ -n "$identity_tmp" ] && [ -f "$identity_tmp" ]; then
        rm -f -- "$identity_tmp"
    fi
}
trap cleanup EXIT HUP INT TERM

if [ "$#" -ne 2 ] || [ "$2" != "--confirm-replace-local-state" ]; then
    printf '%s\n' \
        "Usage: ./scripts/restore-local-state.sh ARCHIVE.tar.gz --confirm-replace-local-state" >&2
    exit 2
fi

archive_path=$1
case "$archive_path" in
    /*) ;;
    *) archive_path="$PROJECT_DIR/$archive_path" ;;
esac
if [ -L "$archive_path" ] || [ ! -f "$archive_path" ]; then
    peos_die "Local-state archive must be an existing regular file, not a link."
fi

peos_validate_volume_name
peos_require_command tar
peos_require_command mktemp
peos_verify_checksum_sidecar "$archive_path"

stage_dir=$(mktemp -d "${TMPDIR:-/tmp}/peos-local-state-restore.XXXXXX")
chmod 700 "$stage_dir"
peos_extract_and_validate_archive "$archive_path" "$stage_dir"
archive_root="$stage_dir/$PEOS_LOCAL_STATE_ROOT"

peos_require_docker
peos_require_services_stopped
peos_require_archive_image

config_dir="$PROJECT_DIR/config"
env_path="$PROJECT_DIR/.env"
identity_path="$config_dir/IDENTITY.local.md"
if [ -L "$config_dir" ] || [ ! -d "$config_dir" ]; then
    peos_die "config must be an existing regular directory, not a link."
fi
if [ -L "$env_path" ] || { [ -e "$env_path" ] && [ ! -f "$env_path" ]; }; then
    peos_die "Existing .env must be a regular file, not a link or directory."
fi
if [ -L "$identity_path" ] || { [ -e "$identity_path" ] && [ ! -f "$identity_path" ]; }; then
    peos_die "Existing config/IDENTITY.local.md must be a regular file, not a link or directory."
fi

env_exists=false
identity_exists=false
volume_exists=false
[ -f "$env_path" ] && env_exists=true
[ -f "$identity_path" ] && identity_exists=true
peos_volume_exists && volume_exists=true

existing_state=false
clean_state=false
if [ "$env_exists" = true ] && [ "$identity_exists" = true ] && [ "$volume_exists" = true ]; then
    existing_state=true
elif [ "$env_exists" = false ] && [ "$identity_exists" = false ] && [ "$volume_exists" = false ]; then
    clean_state=true
else
    peos_die "Refusing partial-state restore. Back up and reconcile .env, identity, and app-data first."
fi

timestamp=$(date -u +"%Y%m%dT%H%M%SZ")
safety_archive=""
if [ "$existing_state" = true ]; then
    safety_archive="$PROJECT_DIR/backups/pre-local-state-restore-$timestamp-$$.tar.gz"
    "$SCRIPT_DIR/backup-local-state.sh" "$safety_archive"
    rollback_stage=$(mktemp -d "${TMPDIR:-/tmp}/peos-local-state-rollback.XXXXXX")
    chmod 700 "$rollback_stage"
    peos_extract_and_validate_archive "$safety_archive" "$rollback_stage"
fi

# Prove the application-data payload can be extracted before touching the live
# volume. The temporary volume is never attached to an application service.
verification_volume="${PEOS_APP_DATA_VOLUME}-restore-check-$$"
peos_create_verification_volume() {
    docker volume create \
        --label "com.personal-execution-os.restore-check=true" \
        "$verification_volume" >/dev/null
}
peos_create_verification_volume
if ! docker run \
    --rm \
    --interactive \
    --network none \
    --read-only \
    --user 0 \
    --volume "$verification_volume:/restore-target" \
    --entrypoint tar \
    "$PEOS_ARCHIVE_IMAGE" \
    -C /restore-target -xf - <"$archive_root/app-data.tar"; then
    peos_die "Application-data verification extraction failed; live state was not changed."
fi
docker volume rm "$verification_volume" >/dev/null
verification_volume=""

if [ "$clean_state" = true ]; then
    peos_create_volume
fi

env_tmp=$(mktemp "$PROJECT_DIR/.env.restore.XXXXXX")
identity_tmp=$(mktemp "$config_dir/.IDENTITY.local.md.restore.XXXXXX")
cp "$archive_root/config.env" "$env_tmp"
cp "$archive_root/IDENTITY.local.md" "$identity_tmp"
chmod 600 "$env_tmp" "$identity_tmp"

restore_failed=false
if ! peos_replace_volume_from_tar "$archive_root/app-data.tar"; then
    restore_failed=true
elif ! mv "$env_tmp" "$env_path"; then
    restore_failed=true
else
    env_tmp=""
    if ! mv "$identity_tmp" "$identity_path"; then
        restore_failed=true
    else
        identity_tmp=""
    fi
fi

if [ "$restore_failed" = true ]; then
    printf '%s\n' "Local-state restore failed; attempting rollback." >&2
    if [ "$existing_state" = true ]; then
        rollback_root="$rollback_stage/$PEOS_LOCAL_STATE_ROOT"
        rollback_ok=true
        peos_replace_volume_from_tar "$rollback_root/app-data.tar" || rollback_ok=false
        cp "$rollback_root/config.env" "$env_path" || rollback_ok=false
        cp "$rollback_root/IDENTITY.local.md" "$identity_path" || rollback_ok=false
        chmod 600 "$env_path" "$identity_path" || rollback_ok=false
        if [ "$rollback_ok" = true ]; then
            printf '%s\n' "Rollback succeeded; requested local state was not installed." >&2
        else
            printf '%s\n' "Rollback failed. Services remain stopped." >&2
            printf '%s\n' "Verified safety archive: $safety_archive" >&2
        fi
    else
        docker volume rm "$PEOS_APP_DATA_VOLUME" >/dev/null 2>&1 || true
        rm -f -- "$env_path" "$identity_path"
        printf '%s\n' "Removed the incomplete clean-install restore; no prior state existed." >&2
    fi
    exit 1
fi

chmod 600 "$env_path" "$identity_path"
printf '%s\n' "Restored local-state archive version $PEOS_LOCAL_STATE_VERSION."
printf '%s\n' "Restored: app-data, .env, and config/IDENTITY.local.md"
printf '%s\n' "PostgreSQL and Redis were not changed. Services remain stopped."
if [ -n "$safety_archive" ]; then
    printf '%s\n' "Pre-restore safety archive: $safety_archive"
fi

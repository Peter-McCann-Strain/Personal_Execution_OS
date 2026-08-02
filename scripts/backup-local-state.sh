#!/bin/sh

set -eu
umask 077

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH='' cd -- "$SCRIPT_DIR/.." && pwd)
# shellcheck source=scripts/local-state-archive-common.sh
. "$SCRIPT_DIR/local-state-archive-common.sh"

timestamp=$(date -u +"%Y%m%dT%H%M%SZ")
output_path=${1:-"$PROJECT_DIR/backups/personal-execution-os-local-state-$timestamp.tar.gz"}
stage_dir=""
partial_path=""
partial_checksum=""

cleanup() {
    if [ -n "$stage_dir" ] && [ -d "$stage_dir" ]; then
        rm -rf -- "$stage_dir"
    fi
    if [ -n "$partial_path" ] && [ -f "$partial_path" ]; then
        rm -f -- "$partial_path"
    fi
    if [ -n "$partial_checksum" ] && [ -f "$partial_checksum" ]; then
        rm -f -- "$partial_checksum"
    fi
}
trap cleanup EXIT HUP INT TERM

if [ "$#" -gt 1 ]; then
    printf '%s\n' "Usage: ./scripts/backup-local-state.sh [OUTPUT.tar.gz]" >&2
    exit 2
fi

case "$output_path" in
    /*) ;;
    *) output_path="$PROJECT_DIR/$output_path" ;;
esac
case "$output_path" in
    *.tar.gz) ;;
    *) peos_die "Local-state backup path must end in .tar.gz." ;;
esac

if [ -e "$output_path" ] || [ -L "$output_path" ]; then
    peos_die "Refusing to overwrite existing local-state backup: $output_path"
fi
if [ -e "$output_path.sha256" ] || [ -L "$output_path.sha256" ]; then
    peos_die "Refusing to overwrite existing checksum sidecar: $output_path.sha256"
fi

output_dir=$(dirname -- "$output_path")
mkdir -p -- "$output_dir"
if [ -L "$output_dir" ] || [ ! -d "$output_dir" ]; then
    peos_die "Backup output directory must be a regular directory, not a link."
fi

env_path="$PROJECT_DIR/.env"
identity_path="$PROJECT_DIR/config/IDENTITY.local.md"
if [ -L "$env_path" ] || [ ! -f "$env_path" ]; then
    peos_die ".env must be an existing regular file, not a link."
fi
if [ -L "$identity_path" ] || [ ! -f "$identity_path" ]; then
    peos_die "config/IDENTITY.local.md must be an existing regular file, not a link."
fi

peos_validate_volume_name
peos_require_command tar
peos_require_command mktemp
peos_require_docker
peos_require_services_stopped
if ! peos_volume_exists; then
    peos_die "Application-data volume does not exist: $PEOS_APP_DATA_VOLUME"
fi
peos_require_archive_image

stage_dir=$(mktemp -d "${TMPDIR:-/tmp}/peos-local-state-backup.XXXXXX")
chmod 700 "$stage_dir"
archive_root="$stage_dir/$PEOS_LOCAL_STATE_ROOT"
mkdir "$archive_root"
chmod 700 "$archive_root"

printf '%s\nversion=%s\n' \
    "$PEOS_LOCAL_STATE_FORMAT" \
    "$PEOS_LOCAL_STATE_VERSION" >"$archive_root/FORMAT"

source_revision=$(git -C "$PROJECT_DIR" rev-parse --verify HEAD 2>/dev/null || printf '%s' "unknown")
case "$source_revision" in
    unknown | [0-9A-Fa-f]*) ;;
    *) source_revision="unknown" ;;
esac
cat >"$archive_root/METADATA" <<EOF
created_at_utc=$timestamp
source_revision=$source_revision
includes=app-data,.env,config/IDENTITY.local.md
excludes=postgresql,redis
EOF

cp "$env_path" "$archive_root/config.env"
cp "$identity_path" "$archive_root/IDENTITY.local.md"
chmod 600 "$archive_root/FORMAT" "$archive_root/METADATA"
chmod 600 "$archive_root/config.env" "$archive_root/IDENTITY.local.md"

docker run \
    --rm \
    --network none \
    --read-only \
    --user 0 \
    --volume "$PEOS_APP_DATA_VOLUME:/archive-source:ro" \
    --entrypoint tar \
    "$PEOS_ARCHIVE_IMAGE" \
    -C /archive-source -cf - . >"$archive_root/app-data.tar"
chmod 600 "$archive_root/app-data.tar"
peos_validate_app_data_tar "$archive_root/app-data.tar" "$stage_dir"

{
    printf '%s  %s\n' "$(peos_sha256 "$archive_root/FORMAT")" "FORMAT"
    printf '%s  %s\n' "$(peos_sha256 "$archive_root/METADATA")" "METADATA"
    printf '%s  %s\n' "$(peos_sha256 "$archive_root/app-data.tar")" "app-data.tar"
    printf '%s  %s\n' "$(peos_sha256 "$archive_root/config.env")" "config.env"
    printf '%s  %s\n' "$(peos_sha256 "$archive_root/IDENTITY.local.md")" "IDENTITY.local.md"
} >"$archive_root/MANIFEST.sha256"
chmod 600 "$archive_root/MANIFEST.sha256"

partial_path=$(mktemp "$output_dir/.personal-execution-os-local-state.XXXXXX")
tar -czf "$partial_path" -C "$stage_dir" "$PEOS_LOCAL_STATE_ROOT"
chmod 600 "$partial_path"

partial_checksum=$(mktemp "$output_dir/.personal-execution-os-local-state-checksum.XXXXXX")
peos_write_checksum_sidecar "$partial_path" "$partial_checksum"
# Bind the sidecar to the final public filename, not the temporary name.
archive_digest=$(peos_sha256 "$partial_path")
printf '%s  %s\n' "$archive_digest" "$(basename -- "$output_path")" >"$partial_checksum"
chmod 600 "$partial_checksum"

mv "$partial_path" "$output_path"
partial_path=""
mv "$partial_checksum" "$output_path.sha256"
partial_checksum=""

printf '%s\n' "Created version $PEOS_LOCAL_STATE_VERSION local-state backup: $output_path"
printf '%s\n' "Created required checksum sidecar: $output_path.sha256"
printf '%s\n' "PostgreSQL and Redis are excluded. Keep this beside a verified database dump."
printf '%s\n' "The archive contains secrets and is not encrypted; encrypt it before off-host storage."

#!/bin/sh

# Shared, POSIX-shell helpers for the versioned local-state backup format.
# This file is sourced by backup-local-state.sh and restore-local-state.sh.

PEOS_LOCAL_STATE_FORMAT="personal-execution-os-local-state"
PEOS_LOCAL_STATE_VERSION="1"
PEOS_LOCAL_STATE_ROOT="${PEOS_LOCAL_STATE_FORMAT}-v${PEOS_LOCAL_STATE_VERSION}"
PEOS_COMPOSE_PROJECT=${COMPOSE_PROJECT_NAME:-personal-execution-os}
PEOS_APP_DATA_VOLUME=${PEOS_APP_DATA_VOLUME:-"${PEOS_COMPOSE_PROJECT}_app-data"}
PEOS_ARCHIVE_IMAGE="redis:7.4.10-alpine3.21@sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2"
# Prevent macOS tar from adding AppleDouble metadata members that are outside
# the deliberately fixed archive schema.
COPYFILE_DISABLE=1
export COPYFILE_DISABLE

peos_die() {
    printf '%s\n' "$*" >&2
    exit 1
}

peos_require_command() {
    command -v "$1" >/dev/null 2>&1 ||
        peos_die "Required command is not available: $1"
}

peos_sha256() (
    file_path=$1
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$file_path" | LC_ALL=C awk 'NR == 1 { print $1 }'
    elif command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$file_path" | LC_ALL=C awk 'NR == 1 { print $1 }'
    else
        peos_die "A SHA-256 utility (shasum or sha256sum) is required."
    fi
)

peos_validate_volume_name() {
    case "$PEOS_APP_DATA_VOLUME" in
        "" | *[!A-Za-z0-9_.-]*)
            peos_die "PEOS_APP_DATA_VOLUME must contain only letters, numbers, '.', '_', or '-'."
            ;;
    esac
}

peos_require_docker() {
    if ! command -v docker >/dev/null 2>&1 || ! docker version >/dev/null 2>&1; then
        peos_die "A running Docker Engine is required."
    fi
}

peos_require_services_stopped() (
    running_containers=$(
        docker ps \
            --filter "label=com.docker.compose.project=$PEOS_COMPOSE_PROJECT" \
            --format '{{.Names}}'
    )
    if [ -n "$running_containers" ]; then
        printf '%s\n' "Refusing while Personal Execution OS services are running:" >&2
        printf '%s\n' "$running_containers" >&2
        printf '%s\n' "Stop them without deleting volumes: docker compose down" >&2
        exit 1
    fi
)

peos_require_archive_image() {
    if ! docker image inspect "$PEOS_ARCHIVE_IMAGE" >/dev/null 2>&1; then
        printf '%s\n' "Fetching the pinned archive helper image..." >&2
        docker pull "$PEOS_ARCHIVE_IMAGE" >/dev/null
    fi
}

peos_volume_exists() {
    docker volume inspect "$PEOS_APP_DATA_VOLUME" >/dev/null 2>&1
}

peos_write_checksum_sidecar() (
    archive_path=$1
    sidecar_path=$2
    archive_name=$(basename -- "$archive_path")
    archive_digest=$(peos_sha256 "$archive_path")
    printf '%s  %s\n' "$archive_digest" "$archive_name" >"$sidecar_path"
)

peos_verify_checksum_sidecar() (
    archive_path=$1
    sidecar_path="$archive_path.sha256"

    if [ -L "$sidecar_path" ] || [ ! -f "$sidecar_path" ]; then
        peos_die "A regular checksum sidecar is required: $sidecar_path"
    fi

    checksum_line=$(
        LC_ALL=C awk '
            NR == 1 { line = $0 }
            END {
                if (NR != 1) {
                    exit 1
                }
                printf "%s", line
            }
        ' "$sidecar_path"
    ) || peos_die "Archive checksum sidecar must contain exactly one record."

    claimed_digest=$(printf '%s\n' "$checksum_line" | LC_ALL=C cut -c 1-64)
    checksum_separator=$(printf '%s\n' "$checksum_line" | LC_ALL=C cut -c 65-66)
    claimed_name=$(printf '%s\n' "$checksum_line" | LC_ALL=C cut -c 67-)

    if [ "${#claimed_digest}" -ne 64 ]; then
        peos_die "Archive checksum sidecar has an invalid SHA-256 digest."
    fi
    case "$claimed_digest" in
        *[!0-9A-Fa-f]*)
            peos_die "Archive checksum sidecar has an invalid SHA-256 digest."
            ;;
    esac
    if [ "$checksum_separator" != "  " ]; then
        peos_die "Archive checksum sidecar must use two spaces before the archive filename."
    fi

    archive_name=$(basename -- "$archive_path")
    if [ "$claimed_name" != "$archive_name" ]; then
        peos_die "Archive checksum sidecar must name the requested archive: $archive_name"
    fi

    actual_digest=$(peos_sha256 "$archive_path")
    claimed_digest=$(printf '%s' "$claimed_digest" | LC_ALL=C tr '[:upper:]' '[:lower:]')
    actual_digest=$(printf '%s' "$actual_digest" | LC_ALL=C tr '[:upper:]' '[:lower:]')
    if [ "$actual_digest" != "$claimed_digest" ]; then
        peos_die "Archive checksum does not match the requested archive: $archive_path"
    fi
)

peos_validate_app_data_tar() (
    app_data_tar=$1
    scratch_dir=$2
    members_path="$scratch_dir/app-data-members.txt"
    verbose_path="$scratch_dir/app-data-members.verbose.txt"

    tar -tf "$app_data_tar" >"$members_path" ||
        peos_die "The application-data payload is not a readable tar archive."
    tar -tvf "$app_data_tar" >"$verbose_path" ||
        peos_die "The application-data payload metadata cannot be read."

    LC_ALL=C awk '
        BEGIN { valid = 1 }
        {
            name = $0
            if (name == "." || name == "./") {
                root_count++
            } else if (substr(name, 1, 2) != "./") {
                valid = 0
            }
            if (name ~ /\\/ || name ~ /(^|\/)\.\.(\/|$)/ || name ~ /\/\//) {
                valid = 0
            }
            if (seen[name]++) {
                valid = 0
            }
        }
        END {
            if (NR == 0 || root_count != 1 || !valid) {
                exit 1
            }
        }
    ' "$members_path" ||
        peos_die "Application-data archive contains an unsafe, duplicate, or non-relative path."

    LC_ALL=C awk '
        substr($1, 1, 1) != "d" && substr($1, 1, 1) != "-" { exit 1 }
    ' "$verbose_path" ||
        peos_die "Application-data archive may contain only directories and regular files."

    member_count=$(LC_ALL=C awk 'END { print NR + 0 }' "$members_path")
    verbose_count=$(LC_ALL=C awk 'END { print NR + 0 }' "$verbose_path")
    if [ "$member_count" -ne "$verbose_count" ]; then
        peos_die "Application-data archive member metadata is inconsistent."
    fi
)

peos_verify_manifest_record() (
    archive_root=$1
    record=$2
    expected_name=$3

    claimed_digest=$(printf '%s\n' "$record" | LC_ALL=C cut -c 1-64)
    separator=$(printf '%s\n' "$record" | LC_ALL=C cut -c 65-66)
    claimed_name=$(printf '%s\n' "$record" | LC_ALL=C cut -c 67-)
    if [ "${#claimed_digest}" -ne 64 ]; then
        peos_die "Archive integrity manifest has an invalid SHA-256 digest."
    fi
    case "$claimed_digest" in
        *[!0-9A-Fa-f]*)
            peos_die "Archive integrity manifest has an invalid SHA-256 digest."
            ;;
    esac
    if [ "$separator" != "  " ] || [ "$claimed_name" != "$expected_name" ]; then
        peos_die "Archive integrity manifest has an unexpected record for $expected_name."
    fi

    actual_digest=$(peos_sha256 "$archive_root/$expected_name")
    claimed_digest=$(printf '%s' "$claimed_digest" | LC_ALL=C tr '[:upper:]' '[:lower:]')
    actual_digest=$(printf '%s' "$actual_digest" | LC_ALL=C tr '[:upper:]' '[:lower:]')
    if [ "$actual_digest" != "$claimed_digest" ]; then
        peos_die "Archive integrity check failed for $expected_name."
    fi
)

peos_extract_and_validate_archive() (
    archive_path=$1
    destination=$2
    outer_members="$destination/outer-members.txt"
    outer_verbose="$destination/outer-members.verbose.txt"

    tar -tzf "$archive_path" >"$outer_members" ||
        peos_die "Local-state archive is not a readable gzip-compressed tar archive."
    tar -tvzf "$archive_path" >"$outer_verbose" ||
        peos_die "Local-state archive metadata cannot be read."

    LC_ALL=C awk -v root="$PEOS_LOCAL_STATE_ROOT" '
        $0 == root "/" { root_dir++; next }
        $0 == root "/FORMAT" { format_file++; next }
        $0 == root "/METADATA" { metadata_file++; next }
        $0 == root "/MANIFEST.sha256" { manifest_file++; next }
        $0 == root "/app-data.tar" { app_data_file++; next }
        $0 == root "/config.env" { env_file++; next }
        $0 == root "/IDENTITY.local.md" { identity_file++; next }
        { unexpected++ }
        END {
            if (NR != 7 || root_dir != 1 || format_file != 1 ||
                metadata_file != 1 || manifest_file != 1 ||
                app_data_file != 1 || env_file != 1 ||
                identity_file != 1 || unexpected != 0) {
                exit 1
            }
        }
    ' "$outer_members" ||
        peos_die "Local-state archive has unexpected, missing, or duplicate members."

    LC_ALL=C awk '
        NR == 1 && substr($1, 1, 1) != "d" { exit 1 }
        NR > 1 && substr($1, 1, 1) != "-" { exit 1 }
        END { if (NR != 7) exit 1 }
    ' "$outer_verbose" ||
        peos_die "Local-state archive contains a link or unsupported member type."

    tar -xzf "$archive_path" -C "$destination" ||
        peos_die "Local-state archive extraction failed."
    archive_root="$destination/$PEOS_LOCAL_STATE_ROOT"

    expected_format=$(printf '%s\nversion=%s' "$PEOS_LOCAL_STATE_FORMAT" "$PEOS_LOCAL_STATE_VERSION")
    actual_format=$(cat "$archive_root/FORMAT")
    if [ "$actual_format" != "$expected_format" ]; then
        peos_die "Unsupported local-state archive format or version."
    fi

    manifest="$archive_root/MANIFEST.sha256"
    manifest_count=$(LC_ALL=C awk 'END { print NR + 0 }' "$manifest")
    if [ "$manifest_count" -ne 5 ]; then
        peos_die "Archive integrity manifest must contain exactly five records."
    fi
    peos_verify_manifest_record "$archive_root" "$(LC_ALL=C sed -n '1p' "$manifest")" "FORMAT"
    peos_verify_manifest_record "$archive_root" "$(LC_ALL=C sed -n '2p' "$manifest")" "METADATA"
    peos_verify_manifest_record "$archive_root" "$(LC_ALL=C sed -n '3p' "$manifest")" "app-data.tar"
    peos_verify_manifest_record "$archive_root" "$(LC_ALL=C sed -n '4p' "$manifest")" "config.env"
    peos_verify_manifest_record "$archive_root" "$(LC_ALL=C sed -n '5p' "$manifest")" "IDENTITY.local.md"

    peos_validate_app_data_tar "$archive_root/app-data.tar" "$destination"
)

peos_create_volume() {
    docker volume create \
        --label "com.docker.compose.project=$PEOS_COMPOSE_PROJECT" \
        --label "com.docker.compose.volume=app-data" \
        "$PEOS_APP_DATA_VOLUME" >/dev/null
}

peos_replace_volume_from_tar() (
    app_data_tar=$1
    docker run \
        --rm \
        --network none \
        --read-only \
        --user 0 \
        --volume "$PEOS_APP_DATA_VOLUME:/restore-target" \
        --entrypoint sh \
        "$PEOS_ARCHIVE_IMAGE" \
        -ec \
        'find /restore-target -mindepth 1 -maxdepth 1 -exec rm -rf -- {} \; && tar -C /restore-target -xf -' \
        <"$app_data_tar"
)

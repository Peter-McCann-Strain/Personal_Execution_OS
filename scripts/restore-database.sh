#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH='' cd -- "$SCRIPT_DIR/.." && pwd)

if [ "$#" -ne 2 ] || [ "$2" != "--confirm-destroy-local-data" ]; then
    echo "Usage: ./scripts/restore-database.sh BACKUP.dump --confirm-destroy-local-data" >&2
    exit 2
fi

backup_path=$1
case "$backup_path" in
    /*) ;;
    *) backup_path="$PROJECT_DIR/$backup_path" ;;
esac

if [ -L "$backup_path" ] || [ ! -f "$backup_path" ]; then
    echo "Backup must be an existing regular file, not a link." >&2
    exit 1
fi

checksum_path="$backup_path.sha256"
if [ -e "$checksum_path" ]; then
    if [ -L "$checksum_path" ] || [ ! -f "$checksum_path" ]; then
        echo "Backup checksum must be a regular file, not a link." >&2
        exit 1
    fi

    if ! checksum_line=$(
        LC_ALL=C awk '
            NR == 1 { line = $0 }
            END {
                if (NR != 1) {
                    exit 1
                }
                printf "%s", line
            }
        ' "$checksum_path"
    ); then
        echo "Backup checksum sidecar must contain exactly one record." >&2
        exit 1
    fi

    claimed_digest=$(printf '%s\n' "$checksum_line" | LC_ALL=C cut -c 1-64)
    checksum_separator=$(printf '%s\n' "$checksum_line" | LC_ALL=C cut -c 65-66)
    claimed_name=$(printf '%s\n' "$checksum_line" | LC_ALL=C cut -c 67-)

    if [ "${#claimed_digest}" -ne 64 ]; then
        echo "Backup checksum sidecar has an invalid SHA-256 digest." >&2
        exit 1
    fi
    case "$claimed_digest" in
        *[!0-9A-Fa-f]*)
            echo "Backup checksum sidecar has an invalid SHA-256 digest." >&2
            exit 1
            ;;
    esac
    if [ "$checksum_separator" != "  " ]; then
        echo "Backup checksum sidecar must use two spaces before the backup filename." >&2
        exit 1
    fi

    backup_name=$(basename -- "$backup_path")
    if [ "$claimed_name" != "$backup_name" ]; then
        echo "Backup checksum sidecar must name the requested archive: $backup_name" >&2
        exit 1
    fi

    if command -v shasum >/dev/null 2>&1; then
        actual_digest=$(shasum -a 256 "$backup_path" | LC_ALL=C awk 'NR == 1 { print $1 }')
    elif command -v sha256sum >/dev/null 2>&1; then
        actual_digest=$(sha256sum "$backup_path" | LC_ALL=C awk 'NR == 1 { print $1 }')
    else
        echo "A SHA-256 utility (shasum or sha256sum) is required." >&2
        exit 1
    fi

    claimed_digest=$(printf '%s' "$claimed_digest" | LC_ALL=C tr '[:upper:]' '[:lower:]')
    actual_digest=$(printf '%s' "$actual_digest" | LC_ALL=C tr '[:upper:]' '[:lower:]')
    if [ "$actual_digest" != "$claimed_digest" ]; then
        echo "Backup checksum does not match the requested archive: $backup_path" >&2
        exit 1
    fi
else
    echo "Warning: no checksum sidecar found at $checksum_path" >&2
fi

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
    echo "Docker with the Compose plugin is required." >&2
    exit 1
fi

cd "$PROJECT_DIR"
docker compose exec -T postgres pg_restore --list <"$backup_path" >/dev/null

timestamp=$(date -u +"%Y%m%dT%H%M%SZ")
safety_backup="$PROJECT_DIR/backups/pre-restore-$timestamp.dump"

# Stop every writer before taking the rollback snapshot so no acknowledged
# writes can occur between the safety dump and database replacement.
docker compose stop web api worker
if ! "$SCRIPT_DIR/backup-database.sh" "$safety_backup"; then
    echo "Could not create the verified safety backup; restoring services." >&2
    docker compose up --detach --wait
    exit 1
fi

restore_archive() {
    archive_path=$1
    docker compose exec -T postgres \
        dropdb -U assistant_admin --if-exists --force personal_execution_os &&
        docker compose exec -T postgres \
            createdb \
                -U assistant_admin \
                -O assistant_migrator \
                personal_execution_os &&
        docker compose exec -T postgres \
            psql \
                -U assistant_admin \
                -d personal_execution_os \
                -v ON_ERROR_STOP=1 <<'SQL' &&
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS ltree;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
SQL
        docker compose exec -T postgres \
            pg_restore \
            -U assistant_migrator \
            -d personal_execution_os \
            --exit-on-error \
            --no-owner \
            --no-privileges \
            --no-comments <"$archive_path"
}

rollback() {
    echo "Restore workflow failed. Attempting automatic rollback from $safety_backup" >&2
    if restore_archive "$safety_backup" &&
        docker compose run --rm migrate &&
        docker compose up --detach --wait; then
        echo "Rollback succeeded; the requested backup was not installed." >&2
        return 0
    else
        echo "Automatic rollback failed. Services remain stopped." >&2
        echo "The verified safety backup is: $safety_backup" >&2
        return 1
    fi
}

if ! restore_archive "$backup_path"; then
    rollback || true
    exit 1
fi

if ! docker compose run --rm migrate; then
    rollback || true
    exit 1
fi
if ! docker compose up --detach --wait; then
    rollback || true
    exit 1
fi

echo "Database restore completed and services are healthy."
echo "Pre-restore safety backup: $safety_backup"

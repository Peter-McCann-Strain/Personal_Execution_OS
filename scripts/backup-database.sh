#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
timestamp=$(date -u +"%Y%m%dT%H%M%SZ")
output_path=${1:-"$PROJECT_DIR/backups/personal-execution-os-$timestamp.dump"}
partial_path=""

cleanup() {
    if [ -n "$partial_path" ] && [ -f "$partial_path" ]; then
        rm -f -- "$partial_path"
    fi
}
trap cleanup EXIT HUP INT TERM

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
    echo "Docker with Compose v2 is required." >&2
    exit 1
fi

case "$output_path" in
    /*) ;;
    *) output_path="$PROJECT_DIR/$output_path" ;;
esac

if [ -e "$output_path" ] || [ -L "$output_path" ]; then
    echo "Refusing to overwrite existing backup: $output_path" >&2
    exit 1
fi

output_dir=$(dirname -- "$output_path")
mkdir -p -- "$output_dir"
umask 077
partial_path=$(mktemp "$output_dir/.personal-execution-os-backup.XXXXXX")

cd "$PROJECT_DIR"
docker compose exec -T postgres \
    pg_dump -U assistant_migrator -d personal_execution_os -Fc >"$partial_path"
docker compose exec -T postgres pg_restore --list <"$partial_path" >/dev/null

# Prove every archive stream can be restored, not merely that its table of
# contents is parseable.
verify_db="peos_backup_verify_$(date -u +%Y%m%d%H%M%S)_$$"
cleanup_verify_db() {
    docker compose exec -T postgres \
        dropdb -U assistant_admin --if-exists --force "$verify_db" >/dev/null 2>&1 || true
}
trap 'cleanup_verify_db; cleanup' EXIT HUP INT TERM
docker compose exec -T postgres \
    createdb -U assistant_admin -O assistant_migrator "$verify_db"
docker compose exec -T postgres \
    psql -U assistant_admin -d "$verify_db" -v ON_ERROR_STOP=1 <<'SQL'
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS ltree;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
SQL
if ! docker compose exec -T postgres \
    pg_restore \
        -U assistant_migrator \
        -d "$verify_db" \
        --exit-on-error \
        --no-owner \
        --no-privileges \
        --no-comments <"$partial_path"; then
    echo "Backup verification restore failed." >&2
    exit 1
fi
cleanup_verify_db

mv "$partial_path" "$output_path"
partial_path=""
chmod 600 "$output_path"

output_name=$(basename -- "$output_path")
if command -v shasum >/dev/null 2>&1; then
    (cd "$output_dir" && shasum -a 256 "$output_name") >"$output_path.sha256"
elif command -v sha256sum >/dev/null 2>&1; then
    (cd "$output_dir" && sha256sum "$output_name") >"$output_path.sha256"
else
    echo "A SHA-256 utility (shasum or sha256sum) is required." >&2
    exit 1
fi
chmod 600 "$output_path.sha256"

echo "Verified PostgreSQL backup and checksum: $output_path"
echo "Back up .env and config/IDENTITY.local.md separately and encrypt every copy."

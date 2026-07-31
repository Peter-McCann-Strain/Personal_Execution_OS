#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
ENV_FILE="$PROJECT_DIR/.env"
IDENTITY_FILE="$PROJECT_DIR/config/IDENTITY.local.md"
TEMP_ENV=""

cleanup() {
    if [ -n "$TEMP_ENV" ] && [ -f "$TEMP_ENV" ]; then
        rm -f -- "$TEMP_ENV"
    fi
}
trap cleanup EXIT HUP INT TERM

if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is required. Install Docker Desktop or another Docker Engine first." >&2
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    echo "Docker is installed but is not running." >&2
    exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
    echo "Docker Compose v2 is required." >&2
    exit 1
fi

cd "$PROJECT_DIR"
umask 077

if [ -L "$IDENTITY_FILE" ] || { [ -e "$IDENTITY_FILE" ] && [ ! -f "$IDENTITY_FILE" ]; }; then
    echo "config/IDENTITY.local.md must be a regular file, not a link or directory." >&2
    exit 1
fi
if [ ! -f "$IDENTITY_FILE" ]; then
    cp config/IDENTITY.example.md "$IDENTITY_FILE"
fi
chmod 600 "$IDENTITY_FILE"

if [ -L "$ENV_FILE" ] || { [ -e "$ENV_FILE" ] && [ ! -f "$ENV_FILE" ]; }; then
    echo ".env must be a regular file, not a link or directory." >&2
    exit 1
fi
if [ ! -f "$ENV_FILE" ]; then
    cp .env.example "$ENV_FILE"
fi
chmod 600 "$ENV_FILE"

read_env_value() {
    key=$1
    awk -F= -v key="$key" '
        $1 == key {
            sub(/^[^=]*=/, "")
            print
            exit
        }
    ' "$ENV_FILE"
}

generate_secret() {
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex 32
    else
        od -An -N32 -tx1 /dev/urandom | tr -d ' \n'
    fi
}

write_env_value() {
    key=$1
    value=$2
    TEMP_ENV=$(mktemp "${TMPDIR:-/tmp}/personal-execution-os-env.XXXXXX")
    awk -v key="$key" -v value="$value" '
        BEGIN { replaced = 0 }
        index($0, key "=") == 1 {
            print key "=" value
            replaced = 1
            next
        }
        { print }
        END {
            if (!replaced) {
                print key "=" value
            }
        }
    ' "$ENV_FILE" >"$TEMP_ENV"
    chmod 600 "$TEMP_ENV"
    mv "$TEMP_ENV" "$ENV_FILE"
    TEMP_ENV=""
}

ensure_secret() {
    key=$1
    placeholder=${2:-}
    value=$(read_env_value "$key")
    if [ -z "$value" ] || { [ -n "$placeholder" ] && [ "$value" = "$placeholder" ]; }; then
        value=$(generate_secret)
        write_env_value "$key" "$value"
    fi
}

ensure_secret POSTGRES_ADMIN_PASSWORD CHANGE_ME_BEFORE_RUNNING
ensure_secret POSTGRES_MIGRATOR_PASSWORD CHANGE_ME_BEFORE_RUNNING
ensure_secret POSTGRES_PASSWORD CHANGE_ME_BEFORE_RUNNING
ensure_secret CONNECTOR_TOKEN_ENCRYPTION_KEY

configured_app_port=$(read_env_value APP_PORT)
app_port=${APP_PORT:-${configured_app_port:-8080}}

case "$app_port" in
    *[!0-9]* | "")
        echo "APP_PORT must be a numeric TCP port." >&2
        exit 1
        ;;
esac
if [ "$app_port" -lt 1 ] || [ "$app_port" -gt 65535 ]; then
    echo "APP_PORT must be between 1 and 65535." >&2
    exit 1
fi

docker compose up --build --detach --wait

echo
echo "Personal Execution OS is ready at http://localhost:${app_port}/setup"
echo "Create the local owner password in your browser to finish setup."

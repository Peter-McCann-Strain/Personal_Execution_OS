#!/bin/sh

set -eu

: "${POSTGRES_MIGRATOR_PASSWORD:?POSTGRES_MIGRATOR_PASSWORD is required}"
: "${POSTGRES_RUNTIME_PASSWORD:?POSTGRES_RUNTIME_PASSWORD is required}"

psql \
    --set=ON_ERROR_STOP=1 \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    --set=migrator_password="$POSTGRES_MIGRATOR_PASSWORD" \
    --set=runtime_password="$POSTGRES_RUNTIME_PASSWORD" <<'SQL'
CREATE ROLE assistant_migrator
    LOGIN
    NOSUPERUSER
    NOCREATEDB
    NOCREATEROLE
    NOINHERIT
    PASSWORD :'migrator_password';

CREATE ROLE assistant_runtime
    LOGIN
    NOSUPERUSER
    NOCREATEDB
    NOCREATEROLE
    NOINHERIT
    PASSWORD :'runtime_password';

ALTER DATABASE personal_execution_os OWNER TO assistant_migrator;
GRANT CONNECT ON DATABASE personal_execution_os TO assistant_runtime;

-- Extension installation requires bootstrap privileges. Migrations retain
-- CREATE EXTENSION IF NOT EXISTS for non-Compose deployments, but the
-- least-privilege migration owner must never be promoted to superuser.
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS ltree;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
SQL

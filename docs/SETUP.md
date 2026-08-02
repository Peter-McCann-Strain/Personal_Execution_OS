# Setup and operations

The supported installation is a local, single-user Docker Compose stack. It
publishes one web port on `127.0.0.1`. PostgreSQL and Redis live on an internal
data network that the web proxy cannot join; the API and worker bridge only the
networks they need.

## Requirements

- A current Docker Engine
- Docker Compose 2.24.0 or later
- macOS or Linux with a POSIX shell; on Windows, use a current WSL 2
  distribution with Docker integration
- At least 4 GB of free memory
- At least 10 GB of free disk space, plus room for your data and backups

CI verifies the Compose stack on Ubuntu. The project has also run its automated
checks on macOS, but it does not yet keep a published host-by-host clean-install
and upgrade record. Other Linux distributions, processor architectures, Docker
alternatives, and Windows configurations may work but are not part of the
tested host matrix.

Confirm Docker is running:

```sh
docker info
docker compose version
```

## Start

From the repository root:

```sh
./scripts/start.sh
```

The script:

1. Copies `.env.example` to a private `.env` file when needed.
2. Creates a private local identity file from the public example.
3. Generates independent database bootstrap, migration, runtime, and
   connector-encryption secrets when they are blank.
4. Builds the pinned container images.
5. Starts PostgreSQL, Redis, migrations, the API, worker, and web service.
6. Waits for the health checks to pass.

PostgreSQL objects belong to a non-superuser migration role. The API and worker
connect through a separate non-owner role, so account row-level-security
policies apply to application queries. Only database initialization and
recovery tools use the bootstrap superuser.

It never prints the generated secrets. Back up `.env` separately from the
database because encrypted connector tokens cannot be recovered without
`CONNECTOR_TOKEN_ENCRYPTION_KEY`.

Open [http://localhost:8080/setup](http://localhost:8080/setup). Create a local
owner password of at least 12 characters. Setup can run once. Later visits open
the sign-in page.

The Security section in Settings can change the password or revoke every
browser session. Both actions sign out every device. There is no email-based
password recovery because the installation has no hosted account service.

Change `APP_PORT` in `.env` before starting if port 8080 is already in use.

## Personal configuration

Edit `config/IDENTITY.local.md` to set local preferences and work rhythms. The
file is mounted read-only into the API and worker containers. It is excluded
from Git and the Docker build context, so it is not stored in an image layer.

Keep both `.env` and `config/IDENTITY.local.md` private. Do not replace the
example files with personal values.

Apply configuration changes with:

```sh
docker compose up --build --detach --wait
```

Proactive automation and session maintenance are off by default. Enabling
`PROACTIVE_AUTOMATION_ENABLED` can schedule model-backed work and incur provider
costs. Enabling `SESSION_MAINTENANCE_ENABLED` allows retention jobs to compact
or remove old runtime transcripts, artifacts, and checkpoints. Review the
configured retention periods and test backup restoration before opting in.
Quality/SLO alert delivery and evaluation export are also disabled until their
destinations and exported-data handling have been reviewed.

## Advanced embedding compatibility

The source includes query-time Ollama and `pgvector` compatibility. The
advanced dataset-curation job also uses Ollama. The public release has no
supported indexing path that populates record embeddings, so this setting does
not enable general semantic record retrieval by itself.

To exercise the compatible code or dataset curation, install Ollama
separately, pull the model named by `OLLAMA_EMBED_MODEL`, then set:

```dotenv
OLLAMA_HOST=http://host.docker.internal:11434
```

Restart the stack after changing `.env`. Leave `OLLAMA_HOST` blank to keep
embedding calls disabled. Structured capture and database retrieval still
work.

## Install the PWA

On the Docker host, open the application in a supported desktop browser and use
the browser's install command.

A phone cannot reach the default `127.0.0.1` binding through the phone's own
`localhost`. Complete the [remote-access steps](#remote-access) first and use a
trusted HTTPS URL before attempting a phone installation. Then, on iOS, use
**Share**, then **Add to Home Screen**. On Android Chromium browsers, use
**Install app** from the browser menu.

The PWA is the supported phone experience. There is no native iOS or Android
binary. The service worker caches application assets only. Personal records,
API responses, authentication state, and page navigations are not available
offline. Phone installation and behavior still require validation on the
specific iOS or Android version you intend to use.

## Enable an integration

All credentialed provider integrations start disabled. Before adding a
credential:

1. Read [INTEGRATIONS.md](INTEGRATIONS.md).
2. Create a dedicated provider credential with the least privilege available.
3. Restrict OAuth scopes, redirect URLs, webhook sources, and allowed users.
4. Put the value in `.env`, not in a tracked file.
5. Restart with `docker compose up --detach --wait`.
6. Test with non-sensitive data.

Google OAuth also depends on `CONNECTOR_TOKEN_ENCRYPTION_KEY`. The start script
creates it, but you must preserve it in encrypted backups. Losing or changing
that value makes stored connector tokens unreadable. Disconnect Google before
rotating the key.

## Check the installation

```sh
curl --fail http://127.0.0.1:8080/healthz
curl --fail http://127.0.0.1:8080/readyz
docker compose ps
```

`healthz` confirms that the API process is alive. `readyz` checks required
dependencies.

View recent logs:

```sh
docker compose logs --tail 200 api worker web
```

Logs can still contain operational metadata. Review them before sharing.

## Stop, restart, and update

Stop processes and preserve data:

```sh
docker compose stop
```

Start them again:

```sh
docker compose start
```

After pulling a reviewed update:

```sh
./scripts/start.sh
```

The migration container runs before the API and worker. Take a backup before
every upgrade and review the release notes for migration or configuration
changes.

The public preview does not yet have version-specific upgrade notes or a
supported downgrade command. Keep the exact source revision used to create
each backup. If an upgrade migration cannot be reversed, recovery may require
restoring both that prior revision and the database dump taken before the
upgrade.

## Back up

Create a PostgreSQL archive:

```sh
docker compose stop web api worker
./scripts/backup-database.sh
```

Stopping application writers first keeps new acknowledged application writes
out of the interval between the database and local-state artifacts. The backup
command parses the archive, restores every archive stream into a temporary
database, removes that database, and writes a SHA-256 sidecar. Keep the dump
and its `.sha256` file together.

This is a database backup, not a complete recovery set. After creating it, stop
the stack without deleting volumes and create the complementary versioned
local-state archive:

```sh
docker compose down
./scripts/backup-local-state.sh
```

The local-state archive includes `.env`, `config/IDENTITY.local.md`, and the
`app-data` volume. It has an internal integrity manifest and a required
archive-bound SHA-256 sidecar. It excludes PostgreSQL and Redis. Follow the
exact sequencing, format, restore, and drill guidance in
[Backup and recovery](BACKUP_AND_RECOVERY.md).

Encrypt backups and keep at least one tested copy on another device. A backup
is not complete until a restore has succeeded in an isolated installation.

Restoring a backup replaces the live local database, so the command requires a
confirmation flag. The script stops writers and creates a verified safety
backup first. If the archive restore, migration, or service startup fails, it
tries to roll back automatically:

```sh
./scripts/restore-database.sh \
  backups/personal-execution-os-YYYYMMDDTHHMMSSZ.dump \
  --confirm-destroy-local-data
```

Test this procedure with disposable data before relying on it.

The database command does not restore Redis queues. Neither does the
local-state helper: Redis is transient coordination state and replaying an old
queue can repeat stale work. Keep the stack stopped until that state and any
external provider effects have been reviewed.

## Retire an installation and remove private data

Stopping containers preserves the installation. Retirement removes it. Use
the following order when you want to end billing and access, remove private
data, and prepare the source tree for public sharing:

1. While the app still runs, disconnect each provider and cancel any paid
   provider, hosting, domain, monitoring, backup, or network service in its own
   console. If in-app revocation fails, revoke the token provider-side before
   continuing.
2. Export anything you intend to keep, then verify the chosen encrypted backup.
   If nothing should survive, identify every dump and external backup for later
   deletion instead.
3. Stop queued and scheduled work, then permanently delete this installation's
   PostgreSQL, Redis, and application-data volumes:

   ```sh
   docker compose down --volumes
   ```

4. Inspect the two ignored private files from the repository root. Once their
   exact paths and contents are confirmed as disposable, delete them:

   ```sh
   ls -l .env config/IDENTITY.local.md
   rm -- .env config/IDENTITY.local.md
   ```

5. Delete operator-chosen database dumps and sidecars, exported datasets,
   logs, screenshots, browser traces, and copied `app-data` artifacts from
   their exact known locations. Do not use a broad recursive deletion command.
6. Use **Clear this device** in Settings before shutdown where possible, then
   clear site data/service workers for every browser profile and device that
   used the app.
7. Apply the retention/deletion controls of each provider and backup service;
   local token revocation cannot erase provider-retained data.
8. Verify that no containers remain, no provider credential still works, no
   heartbeat or alert arrives, and every intended subscription or bill is
   closed.
9. Before publishing the source tree, run the history and working-tree checks
   in [Security](../SECURITY.md#secret-handling). Review every reported
   location; never publish first and plan to clean the history later.

Deleting Docker volumes does not delete `.env`, local identity, browser data,
backups, provider data, or third-party accounts. Removing the source directory
alone is therefore not a complete retirement.

## Prepare a public source build

Distributors can show a source link on the public landing page by setting
`VITE_SOURCE_REPOSITORY_URL` to the repository's HTTPS URL in `.env` before
building. The value is public and becomes part of the web bundle. Leave it
blank for a private fork.

Before publishing, use the latest tagged source revision, complete the
retirement checks above, and run:

```sh
python3 scripts/public_release_audit.py --root . --git-metadata
gitleaks dir . --redact=100
gitleaks git . --redact=100 --log-opts=--all
```

## Remote access

The default port is bound to localhost. Leave it there unless you understand
and can manage the added exposure.

For remote use:

1. Complete first-run owner setup and confirm login locally. The one-time setup
   endpoint has no authentication, so never expose an uninitialized instance
   that another person could claim.
2. Keep the Compose port bound to `127.0.0.1`.
3. Put a maintained TLS reverse proxy or private access network in front of it.
   The outer TLS terminator owns HSTS policy. Enable `includeSubDomains` or
   browser preload only when every affected subdomain is permanently HTTPS.
4. Set `PUBLIC_HOSTNAME` to the exact DNS hostname or IPv4 address sent by that
   proxy, without a scheme, port, path, or wildcard. Configured IPv6 literals
   are not supported; local `[::1]` remains allowed automatically. Requests
   with any other Host are rejected.
5. Set `AUTH_COOKIE_SECURE=true`.
6. Set `AUTH_TRUSTED_ORIGINS` to the exact HTTPS origin.
7. Apply host firewall rules and rate limits.
8. Test login, logout, CSRF rejection, server-sent-event streaming, and
   backup restoration before importing real data.

An installable PWA served to another device needs a secure browser context,
normally HTTPS. A private network does not remove that browser requirement.
Choose and maintain the reverse proxy or private network, certificate
authority, and DNS setup that fit your environment.

Do not publish the PostgreSQL, Redis, API, or worker ports. This repository does
not include a hardened multi-user or public-cloud deployment.

## Development without Compose

Development requires Python 3.12, `uv`, PostgreSQL 16 with `pgvector`, Redis 7,
and Node.js 22 LTS at 22.22 or newer, or Node.js 24 and newer.

The native path is for a disposable development database. It uses the simple
`assistant` owner from `.env.example`, not the three-role Compose security
model, so it is not evidence that runtime RLS or network isolation works.

Create local configuration:

```sh
cp -n .env.example .env
cp -n config/IDENTITY.example.md config/IDENTITY.local.md
chmod 600 .env config/IDENTITY.local.md
```

For a new local PostgreSQL installation, run the equivalent of these commands
as a local database administrator. The password is the development-only value
already present in `.env.example`. Never use it for a remote or real-data
database.

```sh
createuser --login assistant
psql postgres -c "ALTER ROLE assistant PASSWORD 'assistant_dev'"
createdb --owner=assistant personal_execution_os
psql personal_execution_os -c 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'
psql personal_execution_os -c 'CREATE EXTENSION IF NOT EXISTS vector'
psql personal_execution_os -c 'CREATE EXTENSION IF NOT EXISTS ltree'
psql personal_execution_os -c 'CREATE EXTENSION IF NOT EXISTS pg_trgm'
```

If the role or database already exists, inspect it before running any creation
command again. Start the local PostgreSQL and Redis services with the platform
service manager, then confirm:

```sh
psql "postgresql://assistant:assistant_dev@localhost:5432/personal_execution_os" -c 'SELECT 1'
redis-cli -u redis://localhost:6379/0 ping
```

Shells do not automatically export values from `.env`. Either use an
environment loader or export the required values before invoking direct
commands. `uv` itself does not turn `.env` into shell variables for `psql` or
`redis-cli`.

Install dependencies, migrate, and start the API on the port expected by Vite:

```sh
uv sync --frozen --extra dev
uv run alembic upgrade head
uv run uvicorn src.app.main:app --host 127.0.0.1 --port 8001
```

Run the worker in another terminal:

```sh
uv run arq src.app.workers.main.WorkerSettings
```

Run the web client:

```sh
cd frontend
npm ci
npm run dev
```

The frontend listens on `http://localhost:3000` and proxies `/api` to
`http://localhost:8001`. Streaming uses server-sent events; there is no
supported WebSocket endpoint.

To remove only the disposable native database after development, stop the
native API and worker, then run these commands as the same local database
administrator used for creation:

```sh
dropdb --if-exists personal_execution_os
dropuser --if-exists assistant
```

This does not remove `.env`, local identity, Redis keys, browser data, or
operator-created exports. Use the full retirement checklist above when those
must also be removed.

## Validate a source checkout

Backend:

```sh
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run ty check --exit-zero-on-warning
uv run python -m scripts.export_openapi --check
uv run python -m scripts.evaluate validate-assets
uv run pytest tests/unit tests/integration
```

Frontend:

```sh
cd frontend
npm run audit:high
npm run format:check
npm run lint
npm test
npm run build
```

Public-release checks:

```sh
python3 scripts/public_release_audit.py --root .
uv export --frozen --no-dev --no-emit-project \
  --format requirements-txt \
  --output-file /tmp/personal-execution-os-production-requirements.txt
uv run pip-audit --strict \
  --requirement /tmp/personal-execution-os-production-requirements.txt
uv run pre-commit run --all-files
```

## Troubleshooting

- If the stack does not become ready, run `docker compose ps` and inspect the
  migration, API, and worker logs.
- If setup says it has already completed, use the normal sign-in page. Do not
  delete credential rows to bypass authentication.
- If a connector fails, remove its optional credential, restart, and verify its
  provider-side state before retrying.
- If a secret appears in a log, revoke it first. Redaction is defense in depth,
  not permission to log secrets.
- If `.env` is lost, restore it from an encrypted backup. Generating a new
  connector-encryption key does not decrypt existing tokens.

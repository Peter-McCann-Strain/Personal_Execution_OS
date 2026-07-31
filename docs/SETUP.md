# Setup and operations

The supported installation is a local, single-user Docker Compose stack. It
publishes one web port on `127.0.0.1`. PostgreSQL and Redis live on an internal
data network that the web proxy cannot join; the API and worker bridge only the
networks they need.

## Requirements

- A current Docker Engine
- Docker Compose v2
- At least 4 GB of free memory
- At least 10 GB of free disk space, plus room for your data and backups

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

PostgreSQL objects are owned by a non-superuser migration role. The API and
worker connect as a separate non-owner role, so account row-level-security
policies apply to normal application queries. The bootstrap superuser is used
only by the database container's initialization and recovery tools.

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

## Optional local embeddings

Vector search can use an Ollama instance running on the Docker host. Install
Ollama separately, pull the model named by `OLLAMA_EMBED_MODEL`, then set:

```dotenv
OLLAMA_HOST=http://host.docker.internal:11434
```

Restart the stack after changing `.env`. Leave `OLLAMA_HOST` blank to keep
embedding calls disabled. Structured capture and ordinary database retrieval
remain available.

## Install the PWA

Open the application in a supported browser and use the browser's install
command. On iOS, use **Share**, then **Add to Home Screen**. On Android and
desktop Chromium browsers, use **Install app** from the browser menu.

The PWA is the supported phone experience. There is no native iOS or Android
binary. The service worker caches application assets only. Personal records,
API responses, authentication state, and page navigations are not available
offline.

## Enable an integration

All external integrations start disabled. Before adding a credential:

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
every upgrade and review release notes for migration or configuration changes.

## Back up

Create a PostgreSQL archive:

```sh
./scripts/backup-database.sh
```

The command parses the archive, restores every archive stream into a temporary
database, removes that database, and writes a SHA-256 sidecar. Keep the dump and
its `.sha256` file together.

This is a database backup, not a complete machine backup. Also back up:

- `.env`
- `config/IDENTITY.local.md`
- any files stored in the `app-data` Docker volume

Encrypt backups and keep at least one tested copy on another device. A backup
is not complete until a restore has succeeded in an isolated installation.

Restore is intentionally explicit because it replaces the live local database.
The restore script stops writers before creating a verified safety backup. It
attempts to roll back automatically if archive restoration, migration, or
service startup fails:

```sh
./scripts/restore-database.sh \
  backups/personal-execution-os-YYYYMMDDTHHMMSSZ.dump \
  --confirm-destroy-local-data
```

Test this procedure with disposable data before relying on it.

Redis queues are intentionally not restored by this database command. Stop the
stack before a disaster-recovery restore and inspect or clear stale queued jobs
before enabling automation. A fully coherent machine backup must cover the
PostgreSQL dump, `.env`, local identity, `app-data`, Redis state when needed,
and the host configuration under one tested retention policy.

## Remove local data

The following command permanently deletes this installation's PostgreSQL,
Redis, and application-data volumes:

```sh
docker compose down --volumes
```

Disconnect provider accounts first. Provider revocation, provider-retained
data, browser storage, logs, exports, screenshots, and backups have separate
deletion steps. Use **Clear this device** in Settings on each browser.

## Remote access

The default port is intentionally bound to localhost. Keep that boundary unless
you understand the exposure.

For remote use:

1. Complete first-run owner setup and confirm login locally. The one-time setup
   endpoint is intentionally unauthenticated, so never expose an uninitialized
   instance that another person could claim.
2. Keep the Compose port bound to `127.0.0.1`.
3. Put a maintained TLS reverse proxy or private access network in front of it.
4. Set `PUBLIC_HOSTNAME` to the exact DNS hostname or IPv4 address sent by that
   proxy, without a scheme, port, path, or wildcard. Configured IPv6 literals
   are not supported; local `[::1]` remains allowed automatically. Requests
   with any other Host are rejected.
5. Set `AUTH_COOKIE_SECURE=true`.
6. Set `AUTH_TRUSTED_ORIGINS` to the exact HTTPS origin.
7. Apply host firewall rules and rate limits.
8. Test login, logout, CSRF rejection, WebSocket or streaming behavior, and
   backup restoration before importing real data.

Do not publish the PostgreSQL, Redis, API, or worker ports. This repository does
not include a hardened multi-user or public-cloud deployment.

## Development without Compose

Development requires Python 3.12, `uv`, PostgreSQL 16 with `pgvector`, Redis 7,
and Node.js 22 LTS at 22.22 or newer, or Node.js 24 and newer.

```sh
uv sync --frozen --extra dev
uv run alembic upgrade head
uv run uvicorn src.app.main:app --host 127.0.0.1 --port 8000
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
uv run pip-audit --strict
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

# API reference

Personal Execution OS exposes a same-origin JSON API under `/api`. The React
PWA is the primary client. The checked-in OpenAPI document contains the
machine-readable contract:

- `frontend/src/api/generated/openapi.json`
- `frontend/src/api/generated/paths.ts`

Interactive FastAPI docs are available at `/docs`, `/redoc`, and
`/openapi.json` only outside `APP_ENV=production`. The supported Compose stack
runs in production mode, so it does not expose those development surfaces.

## Authentication

Protected routes accept one of:

1. the production browser's signed, revocable session cookie;
2. `X-API-Key: <CHAT_API_KEY>` when the operator explicitly configures that
   server-to-server credential;
3. `Authorization: Bearer <CHAT_API_KEY>` for equivalent explicit automation.

Do not place the API key in browser storage or a public client. Cookie-
authenticated `POST`, `PUT`, `PATCH`, and `DELETE` requests also require:

- an allowed `Origin` when the header is present;
- the CSRF cookie value in `X-CSRF-Token`.

The first-run setup status and initialization routes are public until the
singleton owner credential exists. Never expose an uninitialized installation
to an untrusted network.

## Common request behavior

| Concern | Contract |
| --- | --- |
| Base path | `/api` |
| Content type | JSON unless the route documents a stream or download |
| Request identity | `X-Request-ID` may be accepted or generated; response logs use the resulting ID |
| POST retry identity | Frontend POSTs include `Idempotency-Key`; only registered backend routes receive replay protection |
| Pagination | Most resource lists use `limit` and `offset` and return `items`, `total`, `limit`, and `offset` |
| Dates | ISO 8601 strings; preserve timezone information for instants |
| Identifiers | UUID strings for domain records |
| Errors | Stable HTTP status plus a safe error payload; raw provider, SQL, and exception details are not a contract |

Do not assume that `PUT`, `PATCH`, or `DELETE` is protected by the POST
idempotency middleware. Client-side double-submit prevention remains useful,
but the server operation must still define its own concurrency behavior.

### Idempotent POST contract

For the protected paths below, `Idempotency-Key` is required, must be 1 to 255
characters, and should be globally unique within the installation for at least
24 hours. The server fingerprints method, route template, and up to 1 MiB of
request body.

- same key and body after completion: replay the cached response with
  `Idempotent-Replay: true`, without rerunning the handler;
- same key and a different body or route: `409 idempotency_key_conflict`;
- same key while the first request remains in flight: `409
  idempotency_in_flight`;
- body larger than 1 MiB: `413 payload_too_large`;
- missing/invalid key: `400`;
- unavailable idempotency store: fail closed with `503`;
- expired completed key: start a new attempt.

A handler that never produces a response leaves its key in flight for explicit
operator investigation; the server does not infer safety from elapsed time.
Completed responses, including errors, are cached on a best-effort basis to
preserve at-most-once execution.

The protected route templates are:

```text
POST /api/commitments
POST /api/saved-memories
POST /api/saved-memories/merge
POST /api/projects
POST /api/projects/{project_id}/epics
POST /api/epics/{epic_id}/milestones
POST /api/project-drafts/{draft_id}/apply
POST /api/goals
POST /api/decisions
POST /api/habits
POST /api/habits/{habit_id}/complete
POST /api/notes
POST /api/notes/daily/{note_date}
POST /api/notes/{note_id}/links
POST /api/note-canvases
POST /api/content-assets
POST /api/content-assets/{asset_id}/source-pack
POST /api/scheduled-actions
POST /api/scheduled-actions/{action_id}/run
POST /api/contacts
POST /api/contacts/{contact_id}/interactions
POST /api/connectors/accounts/{account_id}/sync
POST /api/reviews/generate
```

`src/app/api/idempotency.py:_INITIAL_PROTECTED_ROUTES` is the implementation
source of truth. A route change must update this list and this human-facing
contract together; the generated OpenAPI document does not currently express
the middleware-only requirement.

## Resource groups

The generated OpenAPI document contains exact methods, paths, parameters, and
schemas. Human-facing groups are:

- local setup, login, logout, password change, and session revocation;
- account profile and core-data export;
- dashboard and settings;
- goals, projects, tasks, commitments, decisions, habits, and reviews;
- notes, canvases, saved memories, episodes, entities, and search;
- contacts and interactions;
- notifications and Web Push subscriptions;
- read-only calendar, email, and connector sync;
- tutorials and Socratic sessions;
- chat, context inspection, runtime stream, agent runs, and scheduled actions;
- authenticated monitoring and operational evidence.

The public API omits unsupported provider writes.

## Streaming behavior

Two NGINX routes disable proxy buffering:

- `POST /api/chat/stream`
- `GET /api/runtime/stream`

`/api/chat/stream` is server-sent-event delivery, not upstream model-token
streaming. The API finishes `process_message()`, then emits the completed
response progressively in word chunks followed by metadata. Do not design
latency or cancellation behavior as though model generation itself were being
streamed.

`/api/runtime/stream` emits authorized runtime events for the application UI.
Treat identifiers and operational details as sensitive.

The repository has no supported WebSocket endpoint.

## Error shape

Known application errors are mapped in `src/app/core/exceptions.py`. A typical
safe response contains:

```json
{
  "error": "not_found",
  "message": "The requested record was not found",
  "request_id": "..."
}
```

FastAPI validation failures return a stable, safe message without the complete
validation structure. Some authentication dependencies use FastAPI's `detail`
shape. During the public preview, clients should branch primarily on status
and accept either safe envelope.

## Adding or changing a route

1. Update the route and Pydantic contracts.
2. Add unauthorized, success, validation, not-found, and failure tests.
3. Decide whether a POST needs registration in `src/app/api/idempotency.py`.
4. Regenerate:

   ```sh
   uv run python -m scripts.export_openapi
   ```

5. Review the generated diff and update the frontend resource type.
6. Run:

   ```sh
   uv run python -m scripts.export_openapi --check
   uv run pytest tests/contract
   cd frontend
   npm run build
   ```

7. Update privacy, integration, capability, and architecture documentation when
   the contract changes data collection, disclosure, authority, or maturity.

See the [developer API conventions](DEVELOPER_GUIDE.md#api-conventions).

## Related guides

- Read [Architecture: HTTP request lifecycle](ARCHITECTURE.md#http-request-lifecycle)
  to understand authentication, scoping, and persistence.
- Read [Developer guide](DEVELOPER_GUIDE.md) to change an endpoint.

# ADR-0010: Check a generated OpenAPI contract and frontend route map into Git

- **Status:** Accepted (retrospective)
- **Date:** 2026-07-31

## Context

FastAPI and Pydantic define the backend HTTP surface, while the React client
needs stable route paths and request/response expectations. Hand-copying route
strings allows renames and path parameters to drift. Generating artifacts only
at runtime makes review harder and requires a running backend before the
frontend can inspect the contract.

The public production runtime also disables interactive API documentation, so
the source tree needs an auditable contract artifact.

## Decision drivers

- Make API changes visible in code review.
- Give frontend modules one generated route-path source.
- Fail CI when checked-in artifacts do not match FastAPI.
- Fuzz API behavior against the declared schema.
- Keep unsupported routes out of both the documented and frontend surface.

## Considered options

1. Use hand-written route strings and TypeScript interfaces only.
2. Expose OpenAPI at runtime but do not check artifacts into Git.
3. Generate and adopt a complete third-party TypeScript client.
4. Check canonical OpenAPI JSON and a generated TypeScript path map into Git,
   while retaining small hand-written frontend API wrappers.

## Decision

FastAPI's generated OpenAPI schema is exported deterministically to
`frontend/src/api/generated/openapi.json`. The same exporter generates
`paths.ts`, whose named constants are used by frontend API wrappers and
streaming code. CI runs the exporter in check mode and fails when the artifacts
are stale. Schemathesis exercises safe methods against the OpenAPI schema and
keeps response-shape and server-error checks active. It does not yet enforce
all declared status codes or positive/negative input conformance; those gaps
are recorded in the test and roadmap.

The checked route map is not a fully generated type-safe client. Frontend
request and response types still include hand-maintained code, so semantic
contract review remains necessary.

## Consequences

### Positive

- Route additions, removals, and schema changes produce reviewable diffs.
- Frontend paths are less likely to drift from backend registration.
- Contract fuzzing can find response and server-error regressions.
- Development can inspect the API even when production documentation endpoints
  are disabled.

### Negative

- Generated files add repository size and merge noise.
- Developers must regenerate artifacts whenever the schema changes.
- The path map alone does not guarantee TypeScript payload compatibility.
- Dynamic or conditionally omitted routes require deliberate exporter behavior.

### Neutral

- Hand-written API wrappers remain useful for browser concerns such as CSRF,
  streaming, errors, and response adaptation.
- OpenAPI describes supported HTTP behavior, not worker internals or dormant
  compatibility code.

## Security, privacy, and operations

The public artifact must not contain credentials, personal examples, internal
hostnames, or unsupported mutating provider promises. Production disables
runtime `/openapi.json`, Swagger UI, and ReDoc; that reduces exposed discovery
but is not an authorization control.

Contract tests should use fictional data and must not make live provider calls.
Changing authentication, data export, connector, or destructive endpoints
requires security and privacy review in addition to schema regeneration.

## Verification in code and tests

- [`scripts/export_openapi.py`](../../scripts/export_openapi.py) builds and
  checks the deterministic schema and TypeScript route map.
- [`src/app/main.py`](../../src/app/main.py) defines FastAPI metadata, route
  registration, and production documentation behavior.
- [`frontend/src/api/generated/openapi.json`](../../frontend/src/api/generated/openapi.json)
  is the checked schema artifact.
- [`frontend/src/api/generated/paths.ts`](../../frontend/src/api/generated/paths.ts)
  is the checked route map.
- [`frontend/src/api/`](../../frontend/src/api/) and
  [`frontend/src/hooks/use-chat.ts`](../../frontend/src/hooks/use-chat.ts) use
  generated path constants.
- [`tests/unit/test_export_openapi.py`](../../tests/unit/test_export_openapi.py)
  checks path conversion and TypeScript generation.
- [`tests/contract/test_openapi_contract.py`](../../tests/contract/test_openapi_contract.py)
  fuzzes the ASGI application from its schema.
- [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) runs exporter
  check mode.
- [`tests/unit/test_main_app.py`](../../tests/unit/test_main_app.py) checks
  development and production OpenAPI exposure.

## Revisit when

- Hand-maintained payload types cause repeated frontend/backend drift.
- A fully generated client can preserve current CSRF, streaming, and error
  behavior without making the client harder to use.
- Multiple public clients require versioned API compatibility guarantees.
- The checked schema becomes too large or noisy for useful review.

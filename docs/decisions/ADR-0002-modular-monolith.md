# ADR-0002: Keep one modular application rather than split microservices

- **Status:** Accepted (retrospective)
- **Date:** 2026-07-31

## Context

The product spans HTTP APIs, deterministic workflows, model-assisted
workflows, persistence, connectors, scheduled work, and a React client. Most
features share one account boundary and one data model. Splitting those
features into independently deployed services would add network contracts,
distributed failure modes, service discovery, and operational overhead to a
single-owner application.

Some work must still run outside request latency, so the API and worker are
separate processes built from the same backend source.

## Decision drivers

- Keep local deployment and debugging understandable.
- Preserve clear source boundaries without creating distributed systems.
- Reuse one configuration, data model, repository layer, and policy model.
- Run queued and scheduled work separately from HTTP request handling.
- Allow the frontend to remain an independently built static PWA.

## Considered options

1. Split agents, connectors, records, and scheduling into microservices.
2. Build a single server-rendered process with no separate client or worker.
3. Use independent scripts that share the database without an application
   composition root.
4. Use a modular backend monolith, a separate static frontend build, and a
   worker process sharing the backend package.

## Decision

FastAPI is the backend composition root. Backend modules separate HTTP
boundaries, domain services, agent workflows, persistence, cross-cutting core
behavior, and workers. The API and ARQ worker are separate runtime processes
but share `src/app`, configuration, repositories, and PostgreSQL. React is
built separately and served as static assets through NGINX.

Module boundaries are design conventions, not security boundaries or
independently versioned services.

## Consequences

### Positive

- A feature can usually be traced within one repository and transaction model.
- Cross-cutting policies such as account scope and provider availability are
  reusable.
- Local development avoids service discovery and distributed tracing as
  prerequisites.
- The worker isolates slow work without duplicating the domain model.

### Negative

- Large modules can accumulate mixed responsibilities and broad imports.
- API and worker releases remain coupled.
- A defect or dependency in the shared backend package can affect both
  processes.
- Internal module discipline is enforced mainly by review and tests.

### Neutral

- The frontend remains a separate build artifact but not a separately operated
  product.
- Redis and PostgreSQL are infrastructure dependencies, not product-domain
  microservices.

## Security, privacy, and operations

Source modules do not isolate secrets or personal data from one another.
Process and network boundaries in Compose provide some runtime separation, but
both backend processes receive backend configuration and mount application
data. Least-privilege database roles, feature gates, validation, and tests must
therefore carry the security load.

A modular monolith simplifies local operations, but it also means changes to
shared startup, configuration, or persistence deserve API and worker
regression testing.

## Verification in code and tests

- [`src/app/main.py`](../../src/app/main.py) is the FastAPI composition root
  and registers routes, middleware, providers, and process lifecycle.
- [`src/app/domain/services/`](../../src/app/domain/services/) contains
  application workflows; [`src/app/persistence/`](../../src/app/persistence/)
  contains storage behavior; [`src/app/agents/`](../../src/app/agents/) contains
  agent-specific behavior.
- [`src/app/workers/main.py`](../../src/app/workers/main.py) composes the worker
  from the same backend package.
- [`frontend/src/router.tsx`](../../frontend/src/router.tsx) and
  [`frontend/src/api/`](../../frontend/src/api/) show the separately built
  client and HTTP boundary.
- [`tests/unit/test_main_app.py`](../../tests/unit/test_main_app.py) checks
  application composition and route registration.
- [`tests/integration/test_api_endpoints.py`](../../tests/integration/test_api_endpoints.py)
  exercises routes across middleware and service boundaries.
- [`tests/unit/test_worker_main.py`](../../tests/unit/test_worker_main.py)
  checks worker composition.

## Revisit when

- A component needs independent scaling, release cadence, or isolation backed
  by measured operational evidence.
- The backend can no longer be understood or tested through well-defined
  modules.
- Multi-user operation requires independently controlled security domains.
- A proposed service split has a named owner, contract, migration plan, and
  recovery model. Reducing file size alone is not a reason to split a service.

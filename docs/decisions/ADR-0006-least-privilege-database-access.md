# ADR-0006: Separate database authority and enforce account scope in two layers

- **Status:** Accepted (retrospective)
- **Date:** 2026-07-31

## Context

PostgreSQL contains the installation's sensitive durable records. Letting the
API and worker connect as a schema owner or superuser would allow a defect or
compromised runtime to bypass ownership policies and alter the schema. The
current public product supports one local owner, but its inherited schema has
account-scoped rows and should not depend entirely on every query author
remembering an account predicate.

## Decision drivers

- Deny schema and role administration to normal runtime processes.
- Apply account scope even when an application query omits a filter.
- Keep schema migration authority separate from request handling.
- Retain application-layer checks for earlier and clearer failures.
- Keep the isolation controls and document how the single owner maps to them.

## Considered options

1. Use one PostgreSQL superuser for initialization, migrations, API, and worker.
2. Use one non-superuser schema owner and rely on application query filters.
3. Use separate roles but rely only on PostgreSQL RLS.
4. Separate bootstrap, migration, and runtime authority; use PostgreSQL RLS and
   ORM session scoping together.

## Decision

`assistant_admin` performs database bootstrap, `assistant_migrator` owns schema
objects and applies migrations, and `assistant_runtime` serves API and worker
queries without schema-owner or superuser authority. Account-scoped tables use
row-level security. Request and worker sessions set account and user
identifiers transaction-locally. ORM loader criteria and flush guards add a
second application-layer boundary.

The supported single owner maps to fixed initial account and user identifiers.
This does not make the public release a supported multi-tenant system.

## Consequences

### Positive

- A compromised normal runtime has less database authority.
- RLS can reject access that an omitted ORM predicate would otherwise expose.
- ORM guards catch cross-account mutations before or alongside database policy.
- Migration credentials need not be present in the web proxy.

### Negative

- Initialization, grants, migrations, transaction settings, and tests are more
  complex.
- Raw SQL and new tables require deliberate RLS review.
- Retained account infrastructure adds concepts to a single-owner product.
- A migration or grant defect can make the application unavailable.

### Neutral

- RLS is defense in depth, not evidence that multi-user authorization is
  complete.
- The bootstrap administrator still has full authority during initialization
  and recovery.

## Security, privacy, and operations

Role separation limits database damage but cannot defend against a compromised
host administrator, database container, or migration credential. RLS protects
only tables and operations covered by correct policies; extensions, functions,
raw SQL, and future tables require explicit review.

The internal `data` network prevents direct host and web-proxy access to the
database, but it is not an application authorization layer and does not control
the API or worker's outbound Internet access.

Backups and restores use privileged database paths and must be handled as
sensitive administrative operations.

## Verification in code and tests

- [`docker/postgres-init.sh`](../../docker/postgres-init.sh) creates bootstrap,
  migrator, and runtime roles.
- [`scripts/grant_runtime_role.py`](../../scripts/grant_runtime_role.py)
  reconciles runtime grants after migrations.
- [`compose.yml`](../../compose.yml) gives migrations and runtime different
  database URLs.
- [`src/app/persistence/database.py`](../../src/app/persistence/database.py)
  applies ORM loader criteria, flush guards, and PostgreSQL transaction
  settings.
- [`src/app/persistence/migrations/versions/2026_05_18_1000_account_rls_policies.py`](../../src/app/persistence/migrations/versions/2026_05_18_1000_account_rls_policies.py)
  introduces account RLS policies.
- [`tests/unit/test_database.py`](../../tests/unit/test_database.py) checks ORM
  account stamping, filtering, mutation guards, and transaction settings.
- [`tests/integration/test_rls_coverage.py`](../../tests/integration/test_rls_coverage.py)
  checks every required account-scoped public table for RLS and its isolation
  policy.
- [`tests/unit/test_self_hosted_compose.py`](../../tests/unit/test_self_hosted_compose.py)
  checks role and network invariants.

## Revisit when

- The account-scoped schema is removed from the single-owner product.
- A supported multi-user product requires a broader authorization proof.
- PostgreSQL policy complexity exceeds its demonstrated defense-in-depth value.
- A database proxy or managed service changes role and transaction-setting
  semantics.

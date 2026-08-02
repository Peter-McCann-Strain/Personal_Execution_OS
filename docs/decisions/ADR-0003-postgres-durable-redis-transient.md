# ADR-0003: Treat PostgreSQL as durable truth and Redis as transient infrastructure

- **Status:** Accepted (retrospective)
- **Date:** 2026-07-31

## Context

The application needs durable personal records, relational constraints,
full-text search, vector-compatible storage, account scoping, scheduled work,
rate limits, and short-lived coordination. No single storage technology fits
all of those jobs. Recovery must come from durable records, not from whatever
happens to remain in a queue.

## Decision drivers

- Keep personal records and completed outcomes in a transactional store.
- Support PostgreSQL search, extensions, migrations, and row-level security.
- Keep queue and coordination latency away from application database queries.
- Make the durability boundary explainable during backup and recovery.
- Avoid treating an in-memory coordination system as the only copy of a result.

## Considered options

1. Store all records, queues, and coordination state in PostgreSQL.
2. Store application and workflow state primarily in Redis.
3. Introduce separate document, vector, queue, and relational services.
4. Use PostgreSQL for durable truth and Redis for queues, rate limits, and
   short-lived runtime coordination.

## Decision

PostgreSQL is the durable source of truth for application records and durable
runtime results. `pgvector`, full-text search, and other PostgreSQL features
remain in that store. Redis supports ARQ queues, rate limits, notification
coordination, and other short-lived runtime state.

Redis uses append-only persistence and a no-eviction policy in the supported
stack. Those settings improve queue behavior, but PostgreSQL backups still
hold the durable personal records.

## Consequences

### Positive

- Durable records share transactions, constraints, migrations, and access
  policy.
- PostgreSQL backups cover the durable relational records.
- Redis can serve latency-sensitive and expiring coordination use cases.
- Queue loss need not imply loss of already committed application records.

### Negative

- The application operates and monitors two stateful dependencies.
- A Redis loss can discard queued, throttling, or short-lived workflow state.
- Each feature must state which data is durable and which data can be
  reconstructed.
- Database and queue state can be temporally inconsistent during recovery.

### Neutral

- Redis AOF is useful operationally but is outside the PostgreSQL backup tool.
- Some runtime and workflow records remain in PostgreSQL even when Redis
  coordinates their execution.

## Security, privacy, and operations

Both stores can contain sensitive metadata and must remain on the internal data
network. PostgreSQL and Redis volumes are not encrypted by the application.
Host disk encryption, access control, patching, and backup encryption remain
operator responsibilities.

A database restore does not restore Redis. After disaster recovery, the
operator must inspect or clear stale queues before re-enabling automation.
Jobs must be idempotent or record durable execution state where replay could
cause a consequential effect.

## Verification in code and tests

- [`src/app/persistence/database.py`](../../src/app/persistence/database.py)
  creates scoped PostgreSQL sessions.
- [`src/app/persistence/models.py`](../../src/app/persistence/models.py) defines
  durable application and runtime records.
- [`src/app/core/redis.py`](../../src/app/core/redis.py) owns Redis clients and
  transient coordination access.
- [`src/app/workers/main.py`](../../src/app/workers/main.py) registers ARQ jobs
  and schedules.
- [`compose.yml`](../../compose.yml) configures PostgreSQL and Redis volumes,
  Redis AOF, and `noeviction`.
- [`tests/unit/test_database.py`](../../tests/unit/test_database.py) checks
  engine, session, and account-scope behavior.
- [`tests/unit/test_redis.py`](../../tests/unit/test_redis.py) checks Redis
  runtime behavior.
- [`tests/unit/test_self_hosted_compose.py`](../../tests/unit/test_self_hosted_compose.py)
  checks Redis persistence and no-eviction configuration.
- [`tests/unit/test_worker_main.py`](../../tests/unit/test_worker_main.py)
  checks worker job registration.

## Revisit when

- Queue loss causes unacceptable, measured recovery gaps.
- PostgreSQL-backed queues can replace Redis without harming latency or
  operational simplicity.
- Multi-node operation requires a stronger workflow-state consistency model.
- A complete-machine backup format makes coordinated PostgreSQL and Redis
  recovery a supported invariant.

# ADR-0008: Provide verified PostgreSQL backup while documenting full-recovery gaps

- **Status:** Accepted (retrospective)
- **Date:** 2026-07-31

## Context

PostgreSQL holds the durable application records, but a complete
installation also depends on private environment configuration, the local
identity file, encrypted connector-token keys, files in the `app-data` volume,
browser copies, and sometimes Redis queue state. A convenient database dump is
valuable only if its integrity is checked and its narrower scope is not
misrepresented as complete disaster recovery.

Restore is destructive and can fail during archive loading, migrations, or
service restart.

## Decision drivers

- Give operators a repeatable backup for the durable database.
- Detect corrupt, truncated, substituted, or malformed archives early.
- Require explicit confirmation before replacing the live database.
- Preserve a verified pre-restore safety backup and attempt rollback.
- State exactly what the database workflow does not protect.

## Considered options

1. Offer no project backup tooling and rely entirely on Docker volume copies.
2. Copy the live PostgreSQL volume without application-level verification.
3. Claim a PostgreSQL dump is a complete installation backup.
4. Provide a verified PostgreSQL archive and destructive restore workflow,
   while requiring separate full-installation backup coverage.

## Decision

The project supplies a PostgreSQL archive command that parses the archive,
restores every archive stream into a temporary database, and writes a SHA-256
sidecar. Restore verifies the sidecar and archive, stops writers, creates a
verified safety backup, replaces the database, applies migrations, waits for
health, and attempts rollback if the requested restore fails.

This workflow is a database backup, not a full installation backup. A separate
versioned local-state archive covers `.env`, `config/IDENTITY.local.md`, and
the stopped `app-data` volume with a fixed member schema, internal integrity
manifest, and archive-bound checksum. Relevant host and TLS configuration
remain operator-managed, and Redis remains an explicit recovery decision.

## Consequences

### Positive

- Archive creation proves more than `pg_dump` process success.
- Restore refuses an unbound or malformed checksum sidecar.
- A failed restore has a tested automatic rollback path.
- Operators receive an explicit destructive-action boundary.

### Negative

- The supplied commands produce two recovery artifacts rather than one atomic
  complete-machine snapshot.
- The scripts do not encrypt either artifact.
- Database and Redis state may not represent one coherent instant.
- A rollback cannot guarantee recovery from host, Docker, or disk failure.

### Neutral

- Database restore excludes Redis queues. They may need to be cleared instead
  of replayed.
- Browser caches, exports, screenshots, provider-retained data, and old backups
  have independent retention and deletion lifecycles.

## Security, privacy, and operations

Database archives contain sensitive personal records and are not encrypted by
the scripts. The `.env` backup is especially important because losing
`CONNECTOR_TOKEN_ENCRYPTION_KEY` makes stored connector tokens unreadable.
Backups must be encrypted, access-controlled, covered by a retention policy,
and tested on an isolated installation.

A full recovery plan must pair the supported local-state archive with the
PostgreSQL dump. Redis AOF may contain sensitive operational state; restoring
it blindly can replay stale jobs. Operators should stop automation, inspect or
clear queues, and verify provider state after disaster recovery.

## Verification in code and tests

- [`scripts/backup-database.sh`](../../scripts/backup-database.sh) creates,
  parses, test-restores, and checksums PostgreSQL archives.
- [`scripts/restore-database.sh`](../../scripts/restore-database.sh) validates
  input, requires destructive confirmation, creates a safety backup, restores,
  migrates, health-checks, and attempts rollback.
- [`scripts/backup-local-state.sh`](../../scripts/backup-local-state.sh) creates
  the fixed versioned archive for `app-data` and private local configuration.
- [`scripts/restore-local-state.sh`](../../scripts/restore-local-state.sh)
  validates both integrity layers, refuses active services and ambiguous
  partial state, verifies extraction, and preserves a rollback archive.
- [`compose.yml`](../../compose.yml) identifies the separate `postgres-data`,
  `redis-data`, and `app-data` volumes.
- [`scripts/start.sh`](../../scripts/start.sh) creates private configuration and
  the connector-token encryption key that must be preserved separately.
- [`tests/unit/test_database_recovery_scripts.py`](../../tests/unit/test_database_recovery_scripts.py)
  adversarially checks checksum binding, malformed sidecars, actual archive
  hashing, and accepted backup format.
- [`tests/unit/test_self_hosted_compose.py`](../../tests/unit/test_self_hosted_compose.py)
  checks the distinct application-data volume.
- [`tests/unit/test_local_state_recovery_scripts.py`](../../tests/unit/test_local_state_recovery_scripts.py)
  adversarially checks overwrite refusal, stopped-service enforcement,
  permissions, integrity, traversal rejection, restore, and safety backups.
- [`docs/BACKUP_AND_RECOVERY.md`](../BACKUP_AND_RECOVERY.md) defines the exact
  artifact format and operator workflow.

## Revisit when

- Operators require an encrypted, atomic whole-machine snapshot rather than
  the supported paired recovery artifacts.
- Operators require point-in-time recovery or scheduled retention management.
- Restore drills reveal that automatic rollback is insufficient.
- Connector encryption keys move to a supported external secrets manager.

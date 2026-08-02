# Privacy

You operate Personal Execution OS on your own infrastructure. The project does
not run a hosted service or receive your data. Whoever operates the
installation is responsible for privacy notices, legal basis, access controls,
retention, backups, and provider agreements.

This document is an engineering description, not legal advice.

## Data the system can process

Depending on enabled features, an installation may process:

- Conversations, diary entries, notes, memories, goals, projects, tasks, habits,
  reviews, decisions, and commitments
- Contacts, calendar events, email metadata and content
- Message attachments and processing metadata
- Authentication identifiers, connector account identifiers, and webhook data
- Model prompts and outputs, retrieval context, feedback, quality scores, and
  operational traces
- IP addresses, user agents, request identifiers, error data, and performance
  metrics

Assume this data is sensitive even when it is not regulated personal data.

## Where data lives

- PostgreSQL stores durable application records.
- Redis stores queues and short-lived coordination state.
- Docker volumes store database, Redis, and application runtime data.
- Browser storage, caches, service workers, and push subscriptions may retain
  client-side data.
- Logs, evaluation exports, test reports, screenshots, and backups are separate
  copies that require their own retention and access controls.
- Local identity files and `.env` contain personal configuration and secrets.

The repository ignores common runtime locations, but `.gitignore` is not a
security boundary. Do not copy the whole working directory into a release or
support bundle.

The application does not encrypt its PostgreSQL or Redis volumes. Use
full-disk encryption on the host and encrypt every exported backup. Connector
tokens are encrypted with the key in `.env`; application records are not
field-encrypted.

## External disclosures

Data can leave the host when an operator configures and invokes:

- A hosted language-model or embedding provider
- Messaging, email, calendar, or web-search connectors
- Error reporting, analytics, uptime monitoring, or OpenTelemetry export
- Source-control issue filing or other agent tools

The exact payload depends on the feature and may include user text, retrieved
context, contact information, or metadata. Review provider terms, regions,
retention, training controls, subprocessors, access logs, and deletion
mechanisms before enabling an integration.

Blank credentials disable optional integrations in the example configuration.
Do not treat redaction as a substitute for minimizing transmitted data.

[INTEGRATIONS.md](INTEGRATIONS.md) documents the current provider data flows and
disable procedures. Connector sync creates local copies. Revoking a provider
token does not delete those copies, and purging local records does not delete
provider-retained data.

## Operator checklist

- Run locally before exposing the service to a network.
- Use dedicated, least-privilege credentials and separate development accounts.
- Restrict OAuth scopes, webhook sources, redirect URLs, and allowed users.
- Encrypt transport and backups; test restoration and deletion.
- Set retention periods for transcripts, artifacts, checkpoints, logs, traces,
  and backups.
- Keep default PII transmission disabled in telemetry SDKs.
- Avoid recording request bodies, authorization headers, cookies, or connector
  payloads.
- Review browser caches and push subscriptions when removing an account.
- Revoke credentials before sharing logs or reproductions.
- Run `scripts/public_release_audit.py` before publishing any source snapshot.

## Access, export, correction, and deletion

An operator can access and modify records directly in the controlled database
and through application interfaces exposed by the installed version.

The in-app core-data export includes these account-scoped groups:

- episodes, goals, notes, projects, and tasks;
- contacts and interactions;
- reviews, habits, decisions, and commitments;
- saved memories.

It excludes connector-provider data, uploaded or generated files, logs,
caches, backups, browser copies, and external model-provider records. It is not
a complete compliance or portability archive.

A database backup contains the durable PostgreSQL records, but it is not a
complete recovery package. Full recovery may also need `.env`, the
connector-token encryption key, local identity, the application-data volume,
and any operator-owned host or proxy configuration. Redis holds transient
queues and continuity state that the database archive does not reproduce. See
the [backup and recovery guide](BACKUP_AND_RECOVERY.md) and
[architecture boundary](ARCHITECTURE.md#backup-and-recovery-boundary).

This release does not present a one-click account-deletion workflow. The
operator owns the installation and must remove the application's volumes and
the separate copies listed below. Deleting a primary record may not remove
copies from backups, logs, browser caches, model-provider retention, or
connector systems.

A complete deletion process includes:

1. Stop new ingestion and scheduled actions.
2. Revoke connectors, webhooks, sessions, push subscriptions, and credentials.
3. Delete or anonymize application records and remove Docker data volumes.
4. Delete the live `.env` and `config/IDENTITY.local.md` after confirming that
   their exact local copies are no longer required.
5. Use **Clear this device** on each browser, then delete runtime exports, logs,
   screenshots, traces, and other local copies.
6. Apply the backup-retention and destruction policy to dumps, copied
   `app-data`, private configuration, and off-host backups.
7. Submit deletion requests to external providers where required.
8. Verify that scheduled jobs and telemetry no longer emit data and that
   intended paid accounts are closed.

Follow the ordered [installation-retirement
checklist](SETUP.md#retire-an-installation-and-remove-private-data) for exact
repository-local targets and the distinction between stopping and deletion.

## Development and testing

Public tests, examples, and documentation must use fictional identities and
reserved example domains, numbers, and IP ranges. Never derive fixtures from a
production database or conversation transcript.

Privacy regressions are security-relevant. Report suspected exposure privately
under [the security policy](../SECURITY.md).

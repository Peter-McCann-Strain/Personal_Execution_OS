# Product scope

## Purpose

Personal Execution OS helps one person turn scattered input into a repeatable
execution loop:

1. Capture a thought, note, decision, commitment, or piece of work.
2. Organise it into goals, projects, tasks, habits, and knowledge.
3. Plan what matters now.
4. Review what happened and retain useful context.

The intended user is comfortable running a self-hosted application. They
prefer inspectable data, clear approval boundaries, and local control to a
managed consumer service.

## First public release

The first release supports:

- A local owner account with password login and revocable browser sessions
- Notes, diary entries, goals, projects, tasks, commitments, habits, decisions,
  reviews, and saved memories
- Structured search across local records
- An installable desktop and mobile PWA
- Scheduled background processing
- Optional Anthropic model calls
- Optional Telegram capture and notifications
- Optional read-only Google Calendar, Gmail, and Drive sync
- Optional Tavily research, browser push, and operator telemetry
- A documented core-data export and PostgreSQL backup and restore tools

External integrations are disabled by default. Their provider accounts,
retention, deletion, and availability remain outside this project's control.

## Non-goals

This release is not:

- A phone operating system or native mobile application
- A hosted account, synchronization, or backup service
- A multi-user or multi-tenant deployment
- An offline personal-data application
- A replacement for Gmail or Google Calendar
- Open-ended model authority to send, publish, purchase, or delete. Dormant
  ad-hoc tool mutations require per-action confirmation. Explicitly enabled
  notification, alert, push, and issue-filing jobs instead use the operator's
  narrow configuration as standing authorization for their documented side
  effect.
- A complete legal-compliance export or one-click provider deletion system
- A hardened public-internet deployment
- A supported record-embedding/indexing workflow. Query-time Ollama and
  `pgvector` compatibility code exists, but a fresh installation does not
  populate record embeddings.

Calendar, email, and Drive integrations are read-only. The UI and OpenAPI
document omit unsupported actions.

## Maturity

The local installation, authentication, migrations, core APIs, browser client,
and PWA asset boundary are covered by automated tests. The release is still a
public preview because it has not had an independent security assessment or a
large community deployment history.

Operators should start with disposable data, test backup restoration, and
enable one integration at a time.

# Product scope

## Purpose

Personal Execution OS helps one person turn scattered input into a repeatable
execution loop:

1. Capture a thought, note, decision, commitment, or piece of work.
2. Organise it into goals, projects, tasks, habits, and knowledge.
3. Plan what matters now.
4. Review what happened and retain useful context.

The target user is comfortable operating a self-hosted application and values
inspectable data, explicit approval boundaries, and local control more than a
managed consumer experience.

## First public release

The first release supports:

- A local owner account with password login and revocable browser sessions
- Notes, diary entries, goals, projects, tasks, commitments, habits, decisions,
  reviews, and saved memories
- Structured search and optional local vector retrieval
- An installable desktop and mobile PWA
- Scheduled background processing
- Optional Anthropic model calls
- Optional Telegram capture and notifications
- Optional read-only Google Calendar, Gmail, and Drive sync
- Optional Tavily research, browser push, and operator telemetry
- A documented core-data export and PostgreSQL backup and restore tools

External integrations are disabled by default. Their provider accounts,
retention, deletion, and availability remain outside this project's control.

## Deliberate non-goals

This release is not:

- A phone operating system or native mobile application
- A hosted account, synchronization, or backup service
- A multi-user or multi-tenant deployment
- An offline personal-data application
- A replacement for Gmail or Google Calendar
- An autonomous system allowed to send, publish, purchase, or delete without
  confirmation
- A complete legal-compliance export or one-click provider deletion system
- A hardened public-internet deployment

Calendar, email, and Drive integrations are read-only. Unsupported actions are
omitted from the UI and OpenAPI document rather than shown as disabled
promises.

## Maturity

The local installation, authentication, migrations, core APIs, browser client,
and PWA asset boundary are covered by automated tests. The release is still a
public preview because it has not had an independent security assessment or a
large community deployment history.

Operators should start with disposable data, test backup restoration, and
enable one integration at a time.

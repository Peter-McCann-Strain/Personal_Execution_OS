# Capabilities and maturity

Personal Execution OS is a public preview for one self-hosting operator. The
default installation provides a local workspace without a model API key. Some
features need an optional local service, some send data to an external
provider, and some automated systems remain off until the operator enables
them.

The labels below describe what can be used in this release. "Available" means
there is a working user or operator path. It does not mean that the project has
passed an independent security review or been tested by a broad user base.

## Maturity labels

- **Local core:** available in the default Compose installation without an
  external account.
- **Optional provider:** requires a third-party account or delivery network;
  relevant data leaves the host.
- **Operator opt-in:** implemented but disabled initially because it can spend
  money, remove data, or export operational information.
- **Dormant or unsupported:** code may exist for compatibility or development,
  but there is no supported public-release workflow.

## Default local workspace

- **Owner access:** one owner can initialize a password, sign in, change the
  password, and revoke browser sessions. Credentials and session records live
  in PostgreSQL.
- **Planning records:** goals, projects, habits, and decisions have local
  screens. Reviews can assemble local records without a model. Task and
  commitment records are available through their API and capture paths.
- **Knowledge records:** notes and explicit saved memories can be created,
  searched, edited, and deleted. Diary and contact views show records produced
  by their capture paths.
- **Daily views:** Today and Workbench assemble existing PostgreSQL records;
  calendar and mail panels remain unavailable until connected.
- **Structured retrieval:** local records can be filtered and searched without
  vector embeddings.
- **Background work:** the worker exchanges queue state through Redis and
  stores durable results in PostgreSQL.
- **Export and recovery:** Settings exports the documented core record set;
  operator scripts create and restore a checked PostgreSQL archive plus a
  versioned local-state archive for private configuration and `app-data`.
  Redis remains a separate transient-state recovery decision.
- **Installable PWA shell:** versioned static assets can be cached on the
  device. API responses, personal records, authentication state, and
  navigations are not cached for offline use.

The default stack binds to the host's loopback address. Desktop browsers on
that host can use the local PWA path. A phone needs an HTTPS address that can
reach the host, plus the remote-access safeguards in [SETUP.md](SETUP.md).
There is no native iOS or Android application, and personal records are not
available offline.

## Optional external providers

Every provider below starts off. Enabling one accepts that provider's terms,
retention rules, account controls, and availability. Read
[INTEGRATIONS.md](INTEGRATIONS.md) before adding a credential.

- **Anthropic:** prompts, selected context, and model parameters can leave the
  host. Responses and runtime evidence may be stored in PostgreSQL.
- **Google Workspace:** OAuth credentials and read-only requests leave the
  host. Selected Calendar, Gmail, and Drive data is copied into PostgreSQL.
- **Telegram:** messages, attachments, metadata, and delivery requests cross
  the bot network. Captured content and processing records may be stored
  locally.
- **Tavily:** search queries and options leave the host. Results may be stored
  locally or included in a later model request.
- **Browser push:** subscription details and a generic encrypted payload cross
  a browser-vendor push service. Subscription state is stored locally and on
  the device.
- **Sentry:** errors and allowed diagnostic context are retained according to
  the operator's Sentry project.
- **PostHog:** configured events use the literal identifier `anonymous` by
  default; an advanced installation salt makes it pseudonymous.
- **OpenTelemetry:** route, timing, identifier, and configured span attributes
  can be sent to an operator-chosen trace collector. Content export has a
  separate off-by-default control.
- **Healthchecks-compatible endpoint:** a request states that the worker
  reached its checkpoint; retention belongs to that endpoint.

Disconnecting or revoking a provider stops future access but does not by itself
erase local copies, provider-retained data, browser storage, logs, exports, or
backups. [PRIVACY.md](PRIVACY.md) explains the deletion boundaries.

## Disabled-by-default operator systems

These systems are implemented but remain off in the example configuration.

- `PROACTIVE_AUTOMATION_ENABLED=false`: model schedules can incur provider
  cost.
- `SESSION_MAINTENANCE_ENABLED=false`: maintenance compacts or removes old
  runtime evidence under the documented retention policy.
- `AUTO_JUDGE_ENABLED=false`: judging adds model evaluation work.
- Evaluation pipeline, export, spot checks, and dataset curation are off
  because they can add files, provider calls, and review work.
- Cost, quality, schema, dead-letter, and SLO alert delivery is off until an
  operator approves the destination and handling policy.
- `GITHUB_ISSUE_FILER_ENABLED=false`: issue maintenance is an external write
  requiring a dedicated token and repository.

Enable one system at a time and inspect its scheduled work and output. If it
can retain, compact, or delete data, test restoration before switching it on.

Enabling an alert destination, notification channel, Web Push, or GitHub issue
filer gives that specific automation standing permission to deliver its
documented event. It will not ask for confirmation each time. Dormant ad-hoc
tool execution follows a different rule: every proposed mutation needs its own
approval.

## Dormant or unsupported in this release

- MCP compatibility code is disabled. The public release does not provide a
  supported sandboxed MCP runtime.
- The application is not a hosted service, a multi-user deployment, or a
  hardened public-internet installation.
- Calendar, Gmail, and Drive connectors are read-only. The project does not
  send mail or modify provider records through those connectors.
- There is no native mobile binary, background native service, or offline
  personal-record store.
- Query-time Ollama, embedding columns, and `pgvector` search code exist, but
  the public release has no supported workflow that populates record
  embeddings on a fresh installation.
- Model output is not authority to publish, purchase, delete, or perform another
  consequential external action.

See [PRODUCT_SCOPE.md](PRODUCT_SCOPE.md) for the release's non-goals and
[ROADMAP.md](ROADMAP.md) for known work before 1.0.

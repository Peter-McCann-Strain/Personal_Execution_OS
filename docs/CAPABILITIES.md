# Capabilities and maturity

Personal Execution OS is a public preview for one self-hosting operator. The
default installation provides a local workspace without a model API key. Some
features need an optional local service, some send data to an external
provider, and some automated systems remain off until the operator enables
them.

This document records those boundaries. "Available" means the feature has an
implemented user or operator path in this release. It does not mean the project
has completed an independent security review or broad user testing.

## Maturity labels

| Label                  | Meaning                                                                                                        |
| ---------------------- | -------------------------------------------------------------------------------------------------------------- |
| Local core             | Available in the default Compose installation without an external account                                      |
| Optional local         | Requires another service chosen by the operator; data stays local only when that service is local              |
| Optional provider      | Requires a third-party account or delivery network; relevant data leaves the host                              |
| Operator opt-in        | Implemented but disabled by default because it can spend money, remove data, or export operational information |
| Dormant or unsupported | Code may exist for compatibility or development, but there is no supported public-release workflow             |

## Default local workspace

| Capability                       | Maturity   | What works                                                                                                                                                                                                                | Data flow                                                                                                                                                    |
| -------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Owner login and browser sessions | Local core | One local owner can create a password, sign in, change the password, and revoke sessions                                                                                                                                  | Browser to the local web proxy and API; credentials and session records are stored in PostgreSQL                                                             |
| Planning records                 | Local core | Goals, projects, habits, and decisions have local creation and management screens. Reviews can assemble local records without a model. Task and commitment records are also available through their API and capture paths | Browser to API to PostgreSQL                                                                                                                                 |
| Knowledge records                | Local core | Notes and explicit saved memories can be created, searched, edited, and deleted. Diary and contact views display records produced by their capture paths                                                                  | Browser to API to PostgreSQL                                                                                                                                 |
| Today and Workbench views        | Local core | Existing local records are assembled into daily and cross-workspace views                                                                                                                                                 | API reads local PostgreSQL records; optional calendar and mail panels remain unavailable until connected                                                     |
| Structured retrieval             | Local core | Local records can be filtered and searched without vector embeddings                                                                                                                                                      | Browser to API to PostgreSQL                                                                                                                                 |
| Background worker                | Local core | The worker runs beside the API for queued and scheduled jobs                                                                                                                                                              | API and worker exchange queue state through Redis and store durable results in PostgreSQL                                                                    |
| Core data export                 | Local core | The Data section in Settings exports the documented core record set                                                                                                                                                       | API creates a download for the signed-in browser; the downloaded file becomes a separate private copy                                                        |
| Database backup and restore      | Local core | Operator scripts create a checked PostgreSQL archive and can perform an explicit destructive restore                                                                                                                      | PostgreSQL to an operator-chosen file on the host; `.env`, local identity, Redis, and `app-data` need separate backup coverage                               |
| Installable PWA shell            | Local core | Supported browsers can install the responsive web interface                                                                                                                                                               | Static application assets can be cached on the device; API responses, personal records, authentication state, and navigations are not cached for offline use |

The default stack binds to the host's loopback address. Desktop browsers on
that host can use the local PWA path. A phone needs an HTTPS address that can
reach the host, plus the remote-access safeguards in [SETUP.md](SETUP.md).
There is no native iOS or Android application, and personal records are not
available offline.

## Optional local capability

| Capability                               | Maturity       | Enablement                                                                        | Data flow                                                                                                                                                     |
| ---------------------------------------- | -------------- | --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Vector embeddings and semantic retrieval | Optional local | Run Ollama separately, pull the configured embedding model, and set `OLLAMA_HOST` | Selected text is sent to the configured Ollama endpoint. It stays on the operator's systems only when that endpoint is local and under the operator's control |

PostgreSQL `pgvector` stores embeddings after they are created. Leaving
`OLLAMA_HOST` blank disables embedding calls; structured storage and retrieval
continue to work.

## Optional external providers

Every provider in this table starts off. Enabling one accepts that provider's
terms, retention rules, account controls, and availability. Read
[INTEGRATIONS.md](INTEGRATIONS.md) before adding a credential.

| Capability                                                                                                                      | Provider                         | What leaves the host                                                                                          | Local copy or result                                                                                           |
| ------------------------------------------------------------------------------------------------------------------------------- | -------------------------------- | ------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Model-backed chat, diary capture, classification, analysis, commitment extraction, project decomposition, and draft suggestions | Anthropic                        | Prompts, selected workspace context, and model parameters                                                     | Responses and related runtime records can be stored in PostgreSQL                                              |
| Read-only Calendar, Gmail, and Drive sync                                                                                       | Google Workspace                 | OAuth credentials and read-only Google API requests                                                           | Selected event, message, file metadata, and supported file content can be copied into PostgreSQL or `app-data` |
| Message capture and notification delivery                                                                                       | Telegram                         | Messages, attachments, chat metadata, bot requests, and delivery requests                                     | Captured content and processing records can be stored locally                                                  |
| Web research                                                                                                                    | Tavily                           | Search queries and request options                                                                            | Search results can be stored locally or included in a later model request                                      |
| Browser notifications                                                                                                           | Browser vendor push service      | Push subscription details and a generic encrypted notification payload                                        | Subscription state is stored in PostgreSQL and on the browser device                                           |
| Error reporting                                                                                                                 | Sentry                           | Errors and the diagnostic context allowed by the operator's settings                                          | Provider retention depends on the Sentry project                                                               |
| Product telemetry                                                                                                               | PostHog                          | Pseudonymous events and configured properties                                                                 | Provider retention depends on the PostHog project                                                              |
| Traces and metrics                                                                                                              | OpenTelemetry destination        | Routes, timings, identifiers, and configured attributes; content export has a separate off-by-default control | Retention depends on the operator's chosen collector and backend                                               |
| Uptime heartbeat                                                                                                                | Healthchecks-compatible endpoint | A request indicating that a configured job or service reached its checkpoint                                  | Retention depends on the endpoint operator                                                                     |

Disconnecting or revoking a provider stops future access but does not by itself
erase local copies, provider-retained data, browser storage, logs, exports, or
backups. [PRIVACY.md](PRIVACY.md) explains the deletion boundaries.

## Disabled-by-default operator systems

These systems are implemented but deliberately remain off in the example
configuration.

| Control                                                        | Default | Why it is off                                                                                               |
| -------------------------------------------------------------- | ------- | ----------------------------------------------------------------------------------------------------------- |
| `PROACTIVE_AUTOMATION_ENABLED`                                 | `false` | Can schedule model-backed work and incur provider cost                                                      |
| `SESSION_MAINTENANCE_ENABLED`                                  | `false` | Can compact or remove runtime transcripts, artifacts, and checkpoints under the configured retention policy |
| `AUTO_JUDGE_ENABLED`                                           | `false` | Sends or processes additional evaluation work and can increase model use                                    |
| Evaluation pipeline, export, spot checks, and dataset curation | `false` | Can generate extra records, files, provider calls, and review work                                          |
| Cost, quality, schema, dead-letter, and SLO alert delivery     | `false` | Requires an operator-approved destination and handling policy                                               |
| GitHub issue filing                                            | `false` | Creates an external side effect and requires a dedicated token and repository                               |

Do not enable these controls as a bundle. Turn on one system at a time, inspect
its scheduled work and output, and test restoration first when retention or
deletion is involved.

## Dormant or unsupported in this release

- MCP compatibility code is disabled. The public release does not provide a
  supported sandboxed MCP runtime.
- The application is not a hosted service, a multi-user deployment, or a
  hardened public-internet installation.
- Calendar, Gmail, and Drive connectors are read-only. The project does not
  send mail or modify provider records through those connectors.
- There is no native mobile binary, background native service, or offline
  personal-record store.
- Model output is not authority to publish, purchase, delete, or perform another
  consequential external action.

See [PRODUCT_SCOPE.md](PRODUCT_SCOPE.md) for the release's non-goals and
[ROADMAP.md](ROADMAP.md) for known work before 1.0.

# Documentation

Start with the reading path that matches what you need to do. Each guide links
to the next level of detail, so there is no need to read the repository from
front to back.

## Choose a reading path

- **Evaluate:** [Product scope](PRODUCT_SCOPE.md), then
  [capabilities](CAPABILITIES.md) and the [roadmap](ROADMAP.md).
- **Install:** [Setup](SETUP.md), then
  [First ten minutes](FIRST_TEN_MINUTES.md).
- **Understand:** [Architecture](ARCHITECTURE.md), then the
  [decision records](decisions/README.md).
- **Contribute:** [Contributing](../CONTRIBUTING.md), then the
  [developer guide](DEVELOPER_GUIDE.md) and [API contract](API.md).
- **Release:** [Releasing](RELEASING.md), then the
  [security policy](../SECURITY.md).
- **Review security:** [Security policy](../SECURITY.md), then
  [trust boundaries](ARCHITECTURE.md#trust-boundary-model) and
  [privacy](PRIVACY.md).
- **Assess a provider:** [Integrations](INTEGRATIONS.md), then
  [privacy](PRIVACY.md) and [provider setup](SETUP.md#enable-an-integration).
- **Operate or diagnose:** [Setup](SETUP.md), then
  [backup and recovery](BACKUP_AND_RECOVERY.md),
  [configuration](CONFIGURATION.md), and [observability](OBSERVABILITY.md).
- **Review the interface:** [Accessibility](ACCESSIBILITY.md), then the
  [frontend conventions](DEVELOPER_GUIDE.md#frontend-conventions).

## How the pieces fit

Personal Execution OS is a single-owner, self-hosted web application. Its
purpose is to turn captured information into a repeatable loop: capture,
organise, plan, act, and review. The default Docker Compose stack works without
an external model account and binds only to the host's loopback interface.

The React client is an installable PWA. NGINX serves its static files and sends
same-origin `/api` requests to FastAPI. FastAPI authenticates the local owner,
validates requests, and calls application services. PostgreSQL stores durable
records. Redis supports queues, rate limits, and short-lived conversation
state. A separate ARQ worker handles work that should not delay an HTTP
request.

Optional model, search, messaging, Google Workspace, push, and telemetry
providers sit outside the local trust boundary. They start disabled. Enabling
one is an operator decision that can disclose selected data, incur cost, or
create a new availability dependency.

Model reasoning is separate from authority. Models may classify or draft, but
application code validates schemas, scopes data access, records runtime state,
and controls side effects. The supported Google connectors are read-only.
Dormant ad-hoc tool mutations require approval. An operator may also grant
standing permission to a narrowly configured notification, alert, push, or
issue-filing job. Once enabled, that job can perform its documented external
action without asking again for every event.

## Document ownership

Update the relevant documentation in the same change as the implementation:

| Change | Documentation to update |
| --- | --- |
| Supported user behavior or maturity | `CAPABILITIES.md`, possibly `PRODUCT_SCOPE.md` |
| Runtime component, boundary, or data flow | `ARCHITECTURE.md` and its diagrams |
| Contributor workflow or module location | `DEVELOPER_GUIDE.md` |
| A durable technical choice | Add or supersede an ADR under `decisions/` |
| Environment variable or operating command | `.env.example`, `CONFIGURATION.md`, and `SETUP.md` |
| Endpoint, payload, error, or streaming behavior | `API.md`, generated OpenAPI, and the relevant client guide |
| Log, trace, event, alert, or diagnostic identifier | `OBSERVABILITY.md`, `PRIVACY.md`, and `INTEGRATIONS.md` when exported |
| User-interface pattern or interaction | `ACCESSIBILITY.md` and relevant browser/component tests |
| External transmission, retention, or credential | `INTEGRATIONS.md` and `PRIVACY.md` |
| Threat, control, or deployment assumption | `SECURITY.md` and the architecture trust model |
| Known limitation or deferred work | `ROADMAP.md` |
| Frontend build, authentication, or local development | `frontend/README.md` and `DEVELOPER_GUIDE.md` |
| Real-database fixture or integration-test convention | `tests/integration/README.md` and `DEVELOPER_GUIDE.md` |
| Model-price source or snapshot format | `data/prices/README.md` and `OBSERVABILITY.md` |
| Release version or support policy | `CHANGELOG.md`, `SECURITY.md`, and root `README.md` |
| License or attribution | `LICENSE`, `NOTICE`, and package metadata |

Examples and screenshots must use fictional data. Commands should run from the
repository root unless a guide explicitly changes directory.

## Complete index

### Evaluate and operate

- [Product scope](PRODUCT_SCOPE.md): goals, non-goals, and product boundary
- [Capabilities](CAPABILITIES.md): working, optional, gated, and dormant features
- [Setup](SETUP.md): install, update, recover, remotely access, and retire
- [First ten minutes](FIRST_TEN_MINUTES.md): provider-free first workflow
- [Configuration](CONFIGURATION.md): settings, gates, dependencies, and effects
- [Observability](OBSERVABILITY.md): signals, identifiers, privacy, and failure
- [Support](../SUPPORT.md): safe channels and useful diagnostic information
- [Changelog](../CHANGELOG.md): user-visible changes by release

### Understand and assess

- [Architecture](ARCHITECTURE.md): runtime, trust, data, failure, and design
- [Architecture decisions](decisions/README.md): alternatives, consequences,
  and revisit triggers
- [API contract](API.md): authentication, headers, errors, streaming, and
  versioning
- [Integrations](INTEGRATIONS.md): provider data, scopes, retention, and
  disconnection
- [Privacy](PRIVACY.md): storage, export, deletion, and recovery boundaries
- [Security policy](../SECURITY.md): threat model, controls, reporting, and
  hardening
- [Roadmap](ROADMAP.md): known limitations and work before 1.0

### Design and contribute

- [Contributing](../CONTRIBUTING.md): proposal, verification, documentation,
  and review rules
- [Developer guide](DEVELOPER_GUIDE.md): code map, conventions, tests, and
  change recipes
- [Releasing](RELEASING.md): clean audit, exact-commit proof, tagging, and
  publication checks
- [Accessibility](ACCESSIBILITY.md): WCAG target and automated/manual protocol
- [Governance](../GOVERNANCE.md): decisions and maintainer responsibilities
- [Code of Conduct](../CODE_OF_CONDUCT.md): participation and enforcement

### Repository-local references

- [Frontend](../frontend/README.md): browser authentication, build settings,
  commands, and PWA behavior
- [Integration tests](../tests/integration/README.md): real PostgreSQL fixtures,
  Docker behavior, and SQL-test conventions
- [Model-price data](../data/prices/README.md): snapshot schema, sources, and
  update procedure

The index describes the current public-preview documentation set. Use the
capability matrix when implementation exists without a supported user or
operator path.

## Canonical sources and summaries

Some facts appear in more than one guide so that each page makes sense on its
own. The detailed source remains the reference:

- `CONTRIBUTING.md` owns the complete verification command set; README and
  developer-guide commands are scoped entry points.
- `CAPABILITIES.md` owns feature maturity; README contains only orientation.
- `ARCHITECTURE.md` owns current boundaries and flows; ADRs own the decision
  history, alternatives, consequences, and revisit triggers.
- `DEVELOPER_GUIDE.md` owns source navigation and change recipes.
- generated OpenAPI owns machine-readable methods and schemas; `API.md` owns
  middleware conventions and human interpretation.
- `CONFIGURATION.md` owns settings, gates, dependencies, and schedules;
  `SETUP.md` owns operating procedures.

If a summary disagrees with its source, update both in the same change.

## Documentation status

These documents describe the current public-preview source tree. Some dormant
subsystems are present in the code but are not supported. Check the
[capability and maturity matrix](CAPABILITIES.md) when a feature exists without
a documented operator path.

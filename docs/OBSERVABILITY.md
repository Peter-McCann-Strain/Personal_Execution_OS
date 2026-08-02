# Observability

Personal Execution OS provides local structured logs, health checks, durable
runtime records, evaluation evidence, and an authenticated monitoring UI.
External telemetry is optional and disabled until the operator supplies a
destination.

Observability data can itself reveal behavior, timing, identifiers, provider
use, and personal context. It belongs inside the same privacy and backup review
as application records.

## Signals and their source of truth

- **Process logs** in the Docker log driver or local terminal support startup,
  request, worker, provider, and failure diagnosis.
- **Liveness (`/healthz`)** proves only that the API process answers.
- **Readiness (`/readyz`)** checks PostgreSQL and Redis.
- **Preflight (`/health/preflight`)** reports startup configuration checks.
- **Runtime records** in PostgreSQL retain interactions, workflows/steps,
  artifacts, approvals, traces, quality, and failure evidence.
- **Queue state** in Redis plus durable dead-letter records shows in-flight
  work, retries, and terminal failures.
- **Monitoring UI/API** at authenticated `/monitoring` and `/api/ops/*`
  surfaces local health and quality.
- **Browser events** stay in the local UI unless optional PostHog is enabled.
- **External errors/traces** use optional Sentry and OTLP destinations.
- **Heartbeat** uses an optional Healthchecks-compatible URL to show that the
  configured worker checkpoint ran.

Liveness is not readiness. A process can be alive while PostgreSQL or Redis is
unavailable. Preflight is reported separately because some optional or
operator-reviewed conditions do not make the core process unready.

## Correlation identifiers

Use each identifier for its intended lifetime:

| Identifier | Lifetime and purpose |
| --- | --- |
| Request ID | One inbound HTTP request and its structured log context |
| Trace ID | One traced processing path and its child spans |
| Workflow ID | One durable, degradable, resumable, or scheduled unit of work |
| Response ID | One canonical rendered response envelope |
| Interaction ID | One persisted user/assistant interaction record |
| Idempotency key | One logical POST retry identity |

Do not combine these values into a universal identifier. A workflow may outlive
an HTTP request, and a retried POST can involve more than one transport
attempt.

## Local diagnosis

Start with:

```sh
docker compose ps
docker compose logs --tail=200 api
docker compose logs --tail=200 worker
curl --fail http://127.0.0.1:8080/healthz
curl --fail http://127.0.0.1:8080/readyz
```

Then:

1. identify the failing service and request ID;
2. distinguish missing configuration from dependency failure;
3. inspect the authenticated monitoring view for the workflow or interaction;
4. check PostgreSQL durable status before relying on Redis queue state;
5. redact all values before sharing logs or an issue.

Provider errors should have a clear limit and a safe user-facing form. Never
log raw prompts, email, tokens, webhooks, SQL, or connector payloads for
diagnostic convenience.

## Optional external telemetry

### Sentry

Enabled only when `SENTRY_DSN` is set. Keep
`SENTRY_SEND_DEFAULT_PII=false`. Review Sentry project scrubbing, access, and
retention before enabling it.

### PostHog

Enabled only when both the API key and host are configured. Events use the
literal identifier `anonymous` by default. An advanced
`TELEMETRY_INSTALLATION_SALT` changes that to a stable installation-scoped
pseudonymous identifier; pseudonymous is not anonymous. Review properties in
code and at the destination.

### OpenTelemetry

Requires an enabled span exporter and endpoint. The implementation exports
traces; it does not configure an OpenTelemetry metrics pipeline. Collector
headers are secrets. Route names, duration, trace identifiers, model metadata,
and other attributes can still be sensitive.

Content export is a separate control and must remain off unless the destination
is approved to receive personal application content:

```dotenv
OTEL_EXPORT_CONTENT=false
```

Enabling an exporter changes the external data-flow diagram and should be
tested with synthetic traffic first.

### Heartbeat

`HEALTHCHECKS_HEARTBEAT_URL` receives a request from the worker at its scheduled
checkpoint. This grants the destination visibility into host timing and
availability. The inherited `HEALTHCHECKS_BACKUP_URL` setting is not used by
the supported backup scripts.

## Evaluation and alert systems

Evaluation, quality, cost, SLO, schema, dead-letter, export, curation,
spot-check, and GitHub issue systems are independently controlled. Most are off
in `.env.example`.

An enabled alert destination or issue filer uses standing operator
authorization. It can send a message or maintain a GitHub issue without asking
for confirmation for each event. Keep destinations narrow, tokens
least-privilege, and deduplication evidence inspectable.

Runtime evaluation can add model calls and cost. Export can write additional
files to the application-data volume. Retention maintenance can compact or
remove evidence. Enable one subsystem at a time.

## Content and redaction rules

- Keep `PII_REDACTION_ENABLED=true`.
- Keep Sentry default PII and OpenTelemetry content export off.
- Prefer counts, categories, durations, and opaque IDs to content.
- Never log secrets, authorization headers, cookies, prompt bodies, email
  bodies, provider responses, or database exports.
- Redaction is defence in depth; it is not permission to collect a field.
- Treat screenshots, browser traces, Playwright artifacts, and generated
  evaluation reports as potentially sensitive.

## Failure semantics

Observability should not become the authority for the user operation:

- failure to export an optional trace may degrade the request but should not
  invent or duplicate a durable write;
- failure to persist durable application data must roll back;
- failure to persist secondary runtime evidence should be explicit in logs and
  metadata where possible;
- alert delivery failure must not erase the underlying local breach or DLQ
  record;
- a successful heartbeat does not prove backup validity or application-level
  readiness.

## Adding a signal

Before adding a log, metric, event, trace attribute, or export:

1. state the operational question it answers;
2. minimize fields and cardinality;
3. identify whether content or an identifier leaves the host;
4. define retention and deletion at every destination;
5. add redaction and failure tests;
6. keep off-host export blank/off by default;
7. update `CONFIGURATION.md`, `INTEGRATIONS.md`, `PRIVACY.md`, and the threat
   model.

## Related guides

- Use [Configuration](CONFIGURATION.md#observability-and-heartbeat) for exact
  controls.
- Use [Privacy](PRIVACY.md) and [Integrations](INTEGRATIONS.md) before
  enabling a destination.

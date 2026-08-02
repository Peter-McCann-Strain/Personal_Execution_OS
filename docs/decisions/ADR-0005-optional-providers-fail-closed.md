# ADR-0005: Make external providers optional and unavailable by default

- **Status:** Accepted (retrospective)
- **Date:** 2026-07-31

## Context

Model, Google Workspace, Telegram, search, push, analytics, error-reporting,
and observability integrations can add capability, but each introduces cost,
data disclosure, credentials, availability dependencies, and changing provider
terms. Requiring any of them would make the local workspace depend on an
external account and would blur the boundary between stored local records and
transmitted content.

## Decision drivers

- Keep deterministic capture, planning, and retrieval useful without API keys.
- Require separate operator configuration for each external boundary.
- Return a clear unavailable state instead of inventing provider results.
- Prevent retry storms when a model-dependent job is disabled.
- Keep provider credentials out of the web image and public source.

## Considered options

1. Require one hosted model and integration bundle for the application to run.
2. Auto-discover credentials and enable every available integration.
3. Silently substitute placeholder or fabricated results when providers fail.
4. Start providers disabled and give each provider-backed feature its own gate.

## Decision

External providers start disabled or blank in the example configuration.
Provider-independent features continue to work. A provider-backed request
checks configuration and returns a stable unavailable response, skips disabled
scheduled work, or reports degraded readiness as appropriate.

Configuration is per integration. Enabling one provider is not consent to
enable the rest, and successful connectivity is not approval of its retention,
cost, region, or data-use policy.

## Consequences

### Positive

- A new installation works without a model or SaaS account.
- The default installation does not transmit application content to optional
  providers.
- Missing configuration produces testable, explicit behavior.
- Operators can assess and enable providers one at a time.

### Negative

- Some UI and agent features are unavailable in the default installation.
- Every optional feature needs a designed degraded state and tests.
- Provider capability can be fragmented across configuration, readiness, and
  runtime checks.
- Operators remain responsible for provider-side revocation and deletion.

### Neutral

- Advanced Ollama compatibility follows the same explicit-configuration
  principle even when the endpoint is under the operator's control. The public
  release does not include a fresh-install record indexing path.
- Health can be ready while an optional provider is unavailable.

## Security, privacy, and operations

Blank credentials reduce accidental transmission, but environment
configuration is a standing operator opt-in, not a per-request privacy prompt.
Once enabled, model prompts, connector data, search queries, notifications, or
telemetry can leave the host according to that feature's runtime behavior.

Compose network segmentation is not an outbound egress allowlist. The API and
worker can reach external destinations. Operators who need destination
enforcement must add host or network controls outside the application.

Revoking a provider token does not erase local synchronized records, provider
retention, browser copies, exports, logs, or backups.

## Verification in code and tests

- [`.env.example`](../../.env.example) supplies blank credentials and disabled
  operator controls.
- [`src/app/core/llm/provider.py`](../../src/app/core/llm/provider.py) provides
  an explicit disabled model implementation.
- [`src/app/api/deps.py`](../../src/app/api/deps.py) returns a stable unavailable
  response for model-dependent routes.
- [`src/app/core/preflight.py`](../../src/app/core/preflight.py) reports
  configuration readiness.
- [`src/app/workers/agent_tasks.py`](../../src/app/workers/agent_tasks.py) and
  [`src/app/workers/scheduled.py`](../../src/app/workers/scheduled.py) handle
  disabled runtime work.
- [`tests/unit/test_llm_provider.py`](../../tests/unit/test_llm_provider.py)
  checks disabled and configured providers.
- [`tests/unit/test_provider_disabled_runtime.py`](../../tests/unit/test_provider_disabled_runtime.py)
  checks that disabled model work skips without retry or dead-letter noise.
- [`tests/unit/test_preflight.py`](../../tests/unit/test_preflight.py) and
  [`tests/unit/test_provider_readiness.py`](../../tests/unit/test_provider_readiness.py)
  check readiness reporting.

## Revisit when

- A provider-independent local implementation can replace an external
  dependency.
- A supported hosted edition needs different defaults under a separate privacy
  and account model.
- Runtime evidence shows provider checks are inconsistent or can leak data
  before configuration is validated.
- Destination-level egress enforcement becomes a supported deployment feature.

# ADR-0007: Let models propose while deterministic code retains authority

- **Status:** Accepted for dormant compatibility code (retrospective)
- **Date:** 2026-07-31

## Context

Model output can help classify input, retrieve context, draft content, and
propose tool calls. It can also be wrong, manipulated by prompt injection, or
misunderstand the user's destination and intent. Treating free-form output as
authority to send, publish, purchase, modify providers, or delete data would
turn an unreliable inference into a consequential side effect.

The codebase also contains standing operator-controlled automation such as
alerts, browser push, and optional GitHub issue filing. Those controls need to
be described separately from interactive tool approval.

## Decision drivers

- Treat user, connector, webpage, document, and tool content as untrusted.
- Validate schemas, destinations, permissions, and confirmation state in code.
- Preserve useful model-assisted drafting and routing.
- Make cancel, edit, timeout, replay, and audit behavior deterministic.
- Keep unsupported mutating provider actions out of the public workflow.

## Considered options

1. Execute every syntactically valid tool call proposed by a model.
2. Ban all model-proposed tools and allow text generation only.
3. Ask for confirmation after every model operation, including read-only work.
4. Classify risk in code, require confirmation for consequential supported
   tools, and keep model output advisory.

## Decision

In supported features, models may classify, draft, research, and propose
content. Deterministic code owns schemas, database scope, feature gates, and
the narrow standing permission of enabled automations. Supported Google
connectors are read-only, and model output alone is never authority for a
consequential external action.

The codebase also retains a human-in-the-loop design for ad-hoc structured tool
plans. It validates tool support, arguments, destinations, and confirmation
state, with explicit cancellation, edit, timeout, and missing-reply outcomes.
That runtime is compatibility code in this release: application startup never
initializes an MCP client manager, so the public UI/API cannot create and
resume a usable external mutation through it.

## Consequences

### Positive

- Prompt injection or hallucination is less likely to become an immediate
  external mutation.
- The dormant plan design supports inspect, edit, approve, cancel, and trace
  semantics if a future release exposes it.
- Read-only and deterministic local workflows need not prompt unnecessarily.

### Negative

- Retained approval policy and replay-safe workflow state add complexity even
  while the public execution path is dormant.
- Risk classification and tool metadata can be wrong and require testing.
- Dormant compatibility code can be mistaken for a supported public surface.

### Neutral

- Trusted-destination rules and explicit metadata can alter when a supported
  interactive tool prompts; they remain deterministic policy, not model
  discretion.
- Model-free local CRUD uses normal API validation and authentication. It does
  not pass through an agent approval gate.

## Security, privacy, and operations

Dormant interactive HITL approval is not a universal side-effect firewall.
It must not be presented as protection for a path that startup never enables.
Standing
operator opt-ins such as quality or SLO alerts, browser push delivery,
scheduled automation, and GitHub issue filing can perform their configured
delivery behavior without asking for approval on every run. Enabling those
systems is a separate standing authorization that can disclose data or incur
cost. Each must remain disabled initially and must minimize payloads.

Likewise, Compose networks do not restrict backend egress by provider. A
confirmed or standing-enabled action can reach any destination allowed by the
host network unless the operator adds external controls.

Approval previews must mask secrets and treat retrieved content as data rather
than instructions. Timeout and ambiguous resume values fail to cancellation.

## Verification in code and tests

- [`src/app/core/hitl.py`](../../src/app/core/hitl.py) classifies tool risk,
  builds masked previews, handles approval outcomes, and emits approval spans.
- [`src/app/core/confirmation.py`](../../src/app/core/confirmation.py) defines
  deterministic confirmation behavior.
- [`src/app/domain/services/chat.py`](../../src/app/domain/services/chat.py)
  coordinates supported chat execution.
- [`src/app/domain/services/orchestrator.py`](../../src/app/domain/services/orchestrator.py)
  classifies intent for that pipeline.
- [`src/app/agents/graphs/orchestrator.py`](../../src/app/agents/graphs/orchestrator.py)
  is a legacy/dormant graph, not the supported primary chat path.
- [`src/app/main.py`](../../src/app/main.py) does not initialize the retained
  MCP client-manager hook in the public runtime.
- [`src/app/workers/github_filer.py`](../../src/app/workers/github_filer.py),
  [`src/app/domain/services/web_push.py`](../../src/app/domain/services/web_push.py),
  and [`src/app/config.py`](../../src/app/config.py) show separate standing
  opt-in delivery and automation controls.
- [`tests/unit/test_hitl_approval.py`](../../tests/unit/test_hitl_approval.py)
  checks gating, destination handling, secret masking, edit/cancel/timeout, and
  trace behavior.
- [`tests/integration/test_hitl_orchestrator.py`](../../tests/integration/test_hitl_orchestrator.py)
  exercises approve, cancel, and edit behavior in the compatibility design; it
  is not evidence of a public MCP workflow.
- [`tests/unit/test_tool_contracts.py`](../../tests/unit/test_tool_contracts.py)
  checks structured tool contracts.

## Revisit when

- A supported tool cannot be classified reliably by current metadata.
- A new external write path bypasses the documented confirmation or standing
  opt-in model.
- User evidence shows approval fatigue is causing unsafe blanket approval.
- A formally sandboxed MCP runtime becomes a supported product capability.
- Consequential autonomous execution becomes an explicit product goal with a
  separately reviewed policy and audit design.

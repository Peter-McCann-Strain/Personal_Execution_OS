# Architecture decision records

This directory records decisions that materially shape Personal Execution OS.
The records explain the problem, the alternatives considered, the chosen
direction, and the costs accepted with that choice. They complement
[the architecture guide](../ARCHITECTURE.md): the architecture guide describes
the system as a whole, while each record explains one durable decision.

## Retrospective status

ADR-0001 through ADR-0010 were written retrospectively on 2026-07-31 from the
public-preview source tree. They describe the rationale supported by the
current implementation and tests; they are not presented as contemporaneous
minutes from the date the original code was written.

If later evidence shows that a reconstructed rationale is wrong, record the
correction in a new decision and keep the old history visible.

## Decision index

| Record | Decision | Status |
| --- | --- | --- |
| [ADR-0001](ADR-0001-single-owner-compose.md) | Use a single-owner Docker Compose deployment | Accepted (retrospective) |
| [ADR-0002](ADR-0002-modular-monolith.md) | Keep one modular application rather than split microservices | Accepted (retrospective) |
| [ADR-0003](ADR-0003-postgres-durable-redis-transient.md) | Treat PostgreSQL as durable truth and Redis as transient infrastructure | Accepted (retrospective) |
| [ADR-0004](ADR-0004-progressive-web-app.md) | Provide an installable progressive web app rather than native clients | Accepted (retrospective) |
| [ADR-0005](ADR-0005-optional-providers-fail-closed.md) | Make external providers optional and unavailable by default | Accepted (retrospective) |
| [ADR-0006](ADR-0006-least-privilege-database-access.md) | Separate database authority and enforce account scope in two layers | Accepted (retrospective) |
| [ADR-0007](ADR-0007-models-propose-code-authorizes.md) | Let models propose while deterministic code retains authority | Accepted (retrospective) |
| [ADR-0008](ADR-0008-backup-scope.md) | Provide verified PostgreSQL backup while documenting full-recovery gaps | Accepted (retrospective) |
| [ADR-0009](ADR-0009-revocable-browser-sessions.md) | Use revocable server-side browser sessions with CSRF protection | Accepted (retrospective) |
| [ADR-0010](ADR-0010-checked-openapi-contract.md) | Check a generated OpenAPI contract and frontend route map into Git | Accepted (retrospective) |

## Record lifecycle

- **Proposed** records are open for review.
- **Accepted** records describe the current intended direction.
- **Deprecated** records remain informative but should not guide new work.
- **Superseded** records link to the replacement decision.

Do not edit an accepted record merely because the system changes. Add a new
record, describe the new evidence, and mark the old record as superseded. Small
corrections to links, spelling, or verification paths do not require a new
decision.

Each new record should include context, decision drivers, considered options,
the decision, positive and negative consequences, security/privacy/operational
effects, implementation evidence, and concrete conditions that would justify
revisiting the choice.

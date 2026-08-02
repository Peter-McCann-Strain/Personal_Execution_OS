# Roadmap and known debt

Personal Execution OS is a public preview, not a finished 1.0 release. The
current priorities are safer operation, a smaller codebase, and evidence from
real self-hosted use. This list records known work rather than promising a
timeline.

## Before 1.0

### Reliability and operations

- Test explicit Redis recovery choices and stale queue handling. Automated
  fault injection now covers failed database migrations, database rollback,
  local-state replacement, and local-state rollback.
- Publish versioned upgrade notes and a migration compatibility policy.
- Test clean installation and upgrade paths on Linux and macOS hosts.

### Security and privacy

- Commission an independent security assessment.
- Add signed release provenance while keeping container SBOMs and secret scans
  in CI.
- Review remote-only first-run setup so an uninitialized public instance cannot
  be claimed.
- Run deletion and connector-revocation drills against every supported
  integration.

### Maintainability

- Raise backend and frontend coverage floors by testing supported high-risk
  paths first; do not exclude routed pages or consequential automation to
  improve the percentage.
- Declare expected non-success responses for every route, decide and enforce an
  unknown-query-parameter policy, and enable the remaining Schemathesis status
  and positive/negative data conformance checks. The current fuzz gate covers
  safe methods, response shape, and server errors but is not full protocol
  conformance.
- Replace the inherited migration chain with a reviewed public schema baseline
  and a separate, tested upgrade path.
- Remove legacy provider-shaped column names and unused hosted-product tables.
- Remove dormant MCP compatibility code unless a supported sandboxed runtime is
  introduced.

### Product evidence

- Test the PWA on representative iOS and Android devices.
- Validate the planning and review workflows with external self-hosted users.
- Measure import, export, backup, and deletion completeness with realistic
  disposable datasets.
- Keep unsupported provider writes out of the UI and API until their permission,
  confirmation, and audit models are designed and tested.

## Contribution rule

New work should reduce one of these risks or provide clear user evidence. It
should not expand the provider surface, background automation, or data
collection by default.

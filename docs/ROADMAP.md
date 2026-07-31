# Roadmap and known debt

Personal Execution OS is a public preview, not a finished 1.0 release. The
current priorities are safer operation, a smaller codebase, and evidence from
real self-hosted use. This list records known work rather than promising a
timeline.

## Before 1.0

### Reliability and operations

- Add a supported backup path for the application-data volume and private local
  configuration.
- Add a failure-injection recovery drill covering a broken post-restore
  migration and a complete machine-backup format for Redis and `app-data`.
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

- Replace the inherited migration chain with a reviewed public schema baseline
  and a separate, tested upgrade path.
- Remove legacy provider-shaped column names and unused hosted-product tables.
- Remove dormant MCP compatibility code unless a supported sandboxed runtime is
  introduced.
- Split the largest API, worker, and frontend modules into smaller owned
  components.

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

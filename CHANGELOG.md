# Changelog

All notable changes are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) for published
releases.

## Unreleased

## 0.1.1 - 2026-08-02

### Added

- Detailed architecture, setup, API, configuration, observability,
  accessibility, and contributor guides.
- Documentation integrity, Markdown, diagram-rendering, Compose smoke, and
  release-privacy checks in CI.
- OCI source, version, revision, and license metadata for application images.
- Versioned local-state backup and restore helpers for private configuration
  and the application-data volume, with integrity checks and rollback.
- Mandatory API fuzzing, evaluation, backend coverage, and five-profile
  desktop/mobile browser gates.
- Recovery fault-injection tests for failed database migrations, database
  rollback, local-state replacement, and local-state rollback.

### Changed

- Reconciled the in-app welcome page with the public-preview capability
  boundaries.
- Added adopter-facing capability and first-ten-minutes guides.
- Expanded mobile and accessibility release checks.
- Raised frontend coverage above 90% for statements, branches, functions, and
  lines, brought the weakest routed pages above 85% branch coverage, and raised
  the backend no-regression coverage floors.
- Split the largest landing, monitoring, persistence-model, chat-service, and
  tools-handler modules behind stable compatibility facades. Existing routes,
  OpenAPI paths, mapper metadata, and test seams remain unchanged.
- Removed the unsupported Telegram chart command and its browser-dependent
  rendering libraries from the backend image.
- Removed the unfinished prompt A/B runner and its unused statistical helpers.
  The runner used unresolved prompt placeholders, did not perform its claimed
  position-bias reversal, and mislabeled repeated normal confidence intervals
  as an mSPRT. The manual sample-export workflow remains.

### Fixed

- Enforced the Docker Compose version required by the checked-in configuration.
- Added the separate database-role credentials required by the Compose CI job.
- Made Mermaid validation reuse an installed Chrome or Playwright Chromium.
- Corrected account exports for ORM fields whose Python and database names
  differ.
- Prevented the settings screen from exposing complete short API keys.
- Removed the false Tavily sync-connector path and redundant manual
  connector-account creation API, keeping Google OAuth as the credential
  setup path. Corrected Anthropic health status mapping in Settings.
- Applied the morning-briefing UTC fallback consistently to daily planning.
- Hardened malformed runtime-data boundaries found by static analysis and
  adversarial tests, and made a zero-diagnostic type check mandatory in CI.
- Kept Docker stdin attached while restoring local-state archives so the
  application-data payload reaches the verification and replacement
  containers.

## 0.1.0 - 2026-07-31

### Added

- Local single-owner authentication and revocable browser sessions.
- Notes, diary, goals, projects, tasks, commitments, habits, decisions,
  reviews, contacts, tutorials, and saved memory workflows.
- Responsive installable PWA with a static-only service-worker cache.
- Optional Anthropic, Ollama, Google Workspace, Telegram, Tavily, browser push,
  Sentry, PostHog, and OpenTelemetry adapters.
- Least-privilege Compose roles, row-level security, internal data networks,
  health checks, verified PostgreSQL backup and rollback-aware restore tools.
- Unit, integration, contract, evaluation, browser, accessibility, privacy,
  dependency, image, secret, and static-analysis gates.

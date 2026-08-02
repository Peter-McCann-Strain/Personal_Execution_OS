# Security Policy

## Project status

Personal Execution OS is experimental self-hosted software. It has not received
an independent security audit and is not guaranteed suitable for high-risk,
regulated, safety-critical, or multi-tenant use.

The supported version is the latest tagged public-preview release. The default
branch is development code between releases, and older tags may not receive
fixes.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability.

Use GitHub's private vulnerability-reporting or Security Advisory feature when
the published repository has it enabled. If it is unavailable, do not include
vulnerability details in a public issue. Open a minimal issue asking the
maintainer to provide a private reporting channel, or contact the maintainer
through an already published private address. Include in the private report:

- Affected revision or release
- Impact and prerequisites
- Minimal reproduction steps using fictional data
- Relevant logs with all values redacted
- Suggested mitigation, if known

Do not include live credentials, personal records, database exports, or
production endpoint details. Maintainers will respond on a best-effort basis and
may ask for a safer reproduction.

If a credential or personal record has already been exposed, contain the
incident first: revoke the credential, stop the affected integration, preserve
minimal evidence privately, and then report the defect.

## Threat model

The primary risks are:

- Internet access to an incorrectly configured single-user API
- Credential theft from environment files, logs, browser traces, backups, CI,
  or provider consoles
- Prompt injection through email, webpages, documents, or tool output
- Model-generated actions executed without authorization or confirmation
- Cross-account or cross-record access caused by missing ownership checks
- Sensitive payloads sent to telemetry or third-party providers
- Dependency, container, MCP server, and CI supply-chain compromise
- Persistent personal data left in caches, exports, logs, and backups

The project does not claim to defend against a compromised host administrator,
malicious operating-system kernel, physical device compromise, or a provider
that violates its contractual controls.

## Deployment requirements

- Do not expose development servers directly to the internet.
- Terminate TLS at a maintained reverse proxy.
- Configure HSTS at that TLS terminator. Do not opt into subdomain coverage or
  browser preload unless the whole domain satisfies that policy.
- Restrict the API by network and application authentication.
- Generate independent high-entropy secrets; never retain example values.
- Use least-privilege database roles and private service networks.
- Restrict connector scopes, redirect URLs, webhook origins, and allowed users.
- Keep telemetry and issue-filing integrations disabled until you have
  configured and reviewed them.
- Require confirmation for each supported ad-hoc consequential mutation.
  Documented automation may instead use a narrow standing opt-in.
- Pin dependencies and container images for long-lived installations.
- Back up encrypted data and test restoration.
- Keep the host, database, browser, and dependencies patched.

## Secret handling

Secrets belong in `.env` for local development or a secrets manager for
deployment. They must never appear in source, documentation, tests, issue
reports, screenshots, generated API files, Git history, or container layers.

If a secret enters Git history, rewriting the history is not enough. Revoke the
secret at its provider, audit its use, and issue a new credential.

Run before publishing:

```sh
python scripts/public_release_audit.py --root . --git-metadata
gitleaks dir . --redact=100
gitleaks git . --redact=100 --log-opts=--all
```

The release audit prints categories and locations, never detected values.

## Secure contribution rules

- Pull-request workflows use read-only permissions and never
  `pull_request_target`.
- Forked code must not receive repository or deployment secrets.
- CI does not deploy to user infrastructure.
- Security scanners fail closed; broad finding allowlists are not accepted.
- Test fixtures use reserved fictional identities.
- New external data flows require documentation and tests.

See [docs/PRIVACY.md](docs/PRIVACY.md) and
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for data and trust boundaries.

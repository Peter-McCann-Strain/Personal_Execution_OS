# Contributing

Thank you for helping improve Personal Execution OS. Contributions are welcome
when they preserve the project's privacy, safety, and self-hosting goals.

## Before opening a change

1. Search existing issues and pull requests.
2. For substantial behavior or schema changes, open a proposal before writing
   the implementation.
3. Keep each pull request focused on one coherent outcome.
4. Never include real user content, credentials, provider identifiers, personal
   contact details, screenshots of live accounts, or production exports.

Use only fictional examples:

- Email: `user@example.com`
- Phone: `+1 202-555-0100`
- Domain: `example.com`
- Public IP: an address from an RFC 5737 documentation range

## Development setup

Follow [docs/SETUP.md](docs/SETUP.md), then run the relevant checks:

```sh
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run ty check --exit-zero-on-warning
uv run pytest tests/unit tests/integration

cd frontend
npm run format:check
npm run lint
npm run test:coverage
npm run build
```

Before committing, run:

```sh
python3 scripts/public_release_audit.py --root .
uv run pre-commit run --all-files
```

The release audit reports only categories and locations. Do not paste a
detected value into an issue or pull request.

## Pull request requirements

- Add or update tests for behavior changes.
- Document configuration, schema, migration, privacy, or operational changes.
- Keep external integrations disabled by default.
- Preserve human confirmation for consequential external actions.
- Avoid network calls in unit tests.
- Regenerate checked-in API artifacts only from the sanitized source tree.
- Explain new data collection, retention, logging, or third-party transmission.
- Confirm that no secret or personal-data scanner finding is being suppressed
  with a broad allowlist.

Contributions intentionally submitted for inclusion are licensed under Apache
License 2.0, as described in [LICENSE](LICENSE).

## Review

Maintainers may request changes for security, privacy, accessibility,
maintainability, or product-scope reasons. Passing automated checks is necessary
but does not replace human review.

By participating, you agree to follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

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
uv run ty check
uv run pytest tests/unit tests/integration tests/evaluation \
  --cov=src/app --cov-branch --cov-report=xml
uv run python -m scripts.coverage_summary \
  --xml coverage.xml --min-line-rate 0.85 --min-branch-rate 0.67
uv run pytest tests/contract
uv run python -m scripts.export_openapi --check
uv run python -m scripts.evaluate validate-assets
uv run python -m scripts.check_docs
sh -n scripts/*.sh
shellcheck scripts/*.sh
npx --yes markdownlint-cli2@0.23.2
./scripts/check-mermaid.sh

cd frontend
npm run format:check
npm run lint
npm run test:coverage
npm run build
npm run test:e2e:install
npm run test:e2e
```

Docker is required for real-PostgreSQL integration tests and Compose smoke.
The Playwright install command provisions Chromium, Firefox, and WebKit.
`test:e2e` must pass in desktop Chromium, Firefox, and WebKit plus the configured
mobile Chromium and mobile WebKit device profiles. For a focused change, run the
smallest relevant test first; before a pull request, run every applicable
command above.

The coverage thresholds are checked-in no-regression floors, not a claim that
every path is fully tested. New or changed behavior still needs focused tests.

Before committing, run:

```sh
python3 scripts/public_release_audit.py --root . --tracked-only --git-metadata
uv run pre-commit run --all-files
```

The tracked-only audit is suitable after local setup because it ignores `.env`
and other untracked runtime files. Before publishing a source snapshot, remove
private runtime files and run the full working-tree and history checks in
[Security](SECURITY.md#secret-handling). The audit reports only categories and
locations. Do not paste a detected value into an issue or pull request.

## Pull request requirements

- Add or update tests for behavior changes.
- Document configuration, schema, migration, privacy, or operational changes.
- Keep external integrations disabled by default.
- Preserve per-action confirmation for ad-hoc consequential mutations.
  Documented automation may instead use a narrow standing opt-in.
- Avoid network calls in unit tests.
- Regenerate checked-in API artifacts only from the sanitized source tree.
- Explain new data collection, retention, logging, or third-party transmission.
- Update `docs/API.md` for API behavior, `docs/CONFIGURATION.md` for settings,
  `docs/OBSERVABILITY.md` for signals, and `docs/ACCESSIBILITY.md` for UI
  contracts.
- Confirm that no secret or personal-data scanner finding is being suppressed
  with a broad allowlist.

By submitting a contribution for inclusion, you license it under Apache
License 2.0 as described in [LICENSE](LICENSE).

## Review

Maintainers may request changes for security, privacy, accessibility,
maintainability, or product-scope reasons. Passing automated checks is necessary
but does not replace human review.

By participating, you agree to follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

# Releasing

This procedure turns a reviewed commit into a tagged public-preview release.
Run it from a clean clone, not from a working installation. A release is not
ready merely because it builds on a maintainer's machine.

## Preconditions

Before choosing a release commit:

- confirm the version and date in `CHANGELOG.md`;
- keep `pyproject.toml`, `frontend/package.json`, image labels, Compose build
  arguments, the FastAPI version, and the generated OpenAPI document aligned;
- decide which GitHub account and repository are intended to be public;
- remove local identity, credentials, exports, screenshots, reports, database
  dumps, and provider tokens;
- complete the manual accessibility and device evidence that applies to the
  changed workflows;
- record any known limitation that changes the support or security claim.

The release metadata tests enforce the version and source-repository values.
They do not decide whether the named public repository is the right one.

## Verify the source tree

Start from the proposed commit in a fresh clone or a `git archive` extraction.
The source tree must have no uncommitted files:

```sh
git status --short
git show --summary --format=fuller HEAD
python3 scripts/public_release_audit.py --root . --git-metadata
gitleaks git --redact --no-banner .
uv run pre-commit run --all-files
```

The full privacy audit intentionally inspects ignored files. If it reports a
generated coverage file or browser report, remove that generated output from
the release workspace and run the audit again. Do not suppress a finding merely
because Git ignores the file.

## Run the release gates

Use the supported Python and Node.js versions documented in
[Contributing](../CONTRIBUTING.md). Run every backend, contract, evaluation,
frontend, accessibility, dependency, documentation, and Compose gate:

```sh
uv sync --frozen --extra dev
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run ty check
uv run bandit -q -c pyproject.toml -r src/app
uv run pytest tests/unit tests/integration tests/evaluation \
  --cov=src/app --cov-branch --cov-report=xml
uv run python -m scripts.coverage_summary \
  --xml coverage.xml --min-line-rate 0.85 --min-branch-rate 0.67
uv run pytest tests/contract
uv run python -m scripts.export_openapi --check
uv run python -m scripts.evaluate validate-assets
sh -n scripts/*.sh
shellcheck scripts/*.sh
python3 scripts/check_docs.py
npx --yes markdownlint-cli2@0.23.2
./scripts/check-mermaid.sh
```

Then run the frontend gates:

```sh
cd frontend
npm ci
npm run audit:high
npm run format:check
npm run lint
npm run test:coverage
npm run build
npx playwright install
npm run test:e2e
cd ..
```

Run the locked Python dependency audit described in
[Setup](SETUP.md#validate-a-source-checkout). CI also scans the final
backend and web images and publishes CycloneDX SBOM artifacts for review.

## Prove the exact commit

Do not use a developer's existing Compose project for release smoke testing.
Export the proposed commit into a new temporary directory and choose a unique
Compose project name. This prevents the test from reusing or deleting local
application volumes.

```sh
release_root=$(git rev-parse --show-toplevel)
release_commit=$(git -C "$release_root" rev-parse HEAD)
short_revision=$(git -C "$release_root" rev-parse --short=12 "$release_commit")
release_parent=$(dirname -- "$release_root")
release_tmp=$(mktemp -d "$release_parent/peos-release.XXXXXX")
git -C "$release_root" archive "$release_commit" | tar -x -C "$release_tmp"
cd "$release_tmp"
export COMPOSE_PROJECT_NAME="peos-release-$short_revision"
export SOURCE_REVISION="$release_commit"
./scripts/start.sh
```

Keep the rehearsal under a directory Docker Desktop already shares. On macOS,
an individual bind-mounted file from `/tmp` can appear as a directory inside
the container, which prevents PostgreSQL from running its initialization
script. A sibling of the checkout normally sits under the shared `/Users`
tree and avoids that Docker Desktop behavior.

Exercise first-run setup with fictional credentials, check `/readyz`, create
and retrieve a fictional record, make and restore both supported recovery
artifacts, and verify the record and authentication still work. Follow the
coherent recovery-set sequence in
[Backup and recovery](BACKUP_AND_RECOVERY.md#create-a-coherent-recovery-set);
do not treat a database-only restore as the release drill. Inspect both
application images:

```sh
docker image inspect "$(docker compose images -q api)"
docker image inspect "$(docker compose images -q web)"
```

Confirm the OCI version, source, revision, and licence labels match the release
commit. Tear down only the disposable project named in
`COMPOSE_PROJECT_NAME`:

```sh
docker compose down --volumes --remove-orphans --rmi local
```

The temporary directory contains generated secrets. Remove it through the
operating system's normal file-management controls after the audit record is
complete.

## Tag and publish

Create an annotated tag only after the exact commit has passed:

```sh
git tag -a v0.1.1 -m "Personal Execution OS v0.1.1"
git push origin main
git push origin v0.1.1
```

Protect `main`, require the documentation, backend and evaluation, API
contract, frontend, Compose, dependency, secret-scan, and CodeQL checks, and
prevent force pushes. A public GitHub release should link to the changelog,
identify the tested commit, repeat the public-preview warning, and attach or
link the CI-generated SBOMs.

Do not call the release signed or reproducible unless the corresponding
provenance has actually been generated and independently verified.

## After publication

From a machine without the development checkout:

1. clone the public repository by tag;
2. follow only the published setup guide;
3. complete first-run login and the first-ten-minutes walkthrough;
4. verify backup and restore with fictional records;
5. open every documentation link from the rendered GitHub pages;
6. record the operating system, Docker and Compose versions, browser, result,
   and any deviation from the guide.

If the clean public install fails, fix the release or mark it withdrawn. Do not
silently move an existing tag.

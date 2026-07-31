# Governance

Personal Execution OS is currently a single-maintainer public-preview project.
The owner of the canonical repository is the release maintainer and final
decision maker until a broader maintainer group is documented here.

## Decisions

- Small fixes can proceed through a focused pull request.
- New data flows, integrations, schema changes, automation, or product-scope
  changes should begin with a public proposal.
- Decisions should cite user evidence, operational risk, or a documented
  product constraint.
- Passing tests is required but does not override privacy, security,
  accessibility, or scope concerns.

When proposals conflict, the maintainer prefers the change that keeps data
local, reduces irreversible behavior, narrows external permissions, and leaves
the installation understandable to its operator.

## Releases

The release maintainer:

1. Reviews the diff and migration impact.
2. Runs the documented release gates.
3. Updates `CHANGELOG.md` and upgrade notes.
4. Creates a signed or otherwise verifiable tag when release provenance is
   available.
5. Publishes known limitations rather than silently accepting a failed gate.

This preview has no guaranteed release cadence or support service-level
agreement.

## Maintainer changes

Additional maintainers may be added after sustained, constructive
contributions and demonstrated care for the project's trust boundaries.
Changes to maintainership are recorded in this file and announced through the
canonical repository.

## Conduct and security

Community behavior follows `CODE_OF_CONDUCT.md`. Security reports use the
private process in `SECURITY.md`; do not open a public issue for a
vulnerability or include private workspace data in any report.

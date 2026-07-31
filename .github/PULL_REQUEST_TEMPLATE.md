## Outcome

Describe the user or operator outcome this change completes.

## Evidence

List the checks run and attach only synthetic or redacted evidence.

## Trust boundaries

- [ ] External integrations remain disabled by default.
- [ ] New data collection, retention, logging, or third-party transmission is
      documented.
- [ ] Consequential external actions retain explicit human confirmation.
- [ ] No credentials, personal data, provider identifiers, private logs, or
      production exports are included.

## Change checks

- [ ] Tests cover the behavior and failure path.
- [ ] Configuration, schema, migrations, operations, and user documentation are
      updated where relevant.
- [ ] Accessibility and responsive behavior were checked for UI changes.
- [ ] `python3 scripts/public_release_audit.py --root .` reports zero findings.
- [ ] The relevant commands in `CONTRIBUTING.md` pass.

## Release notes

State the changelog entry or explain why the change does not affect users.

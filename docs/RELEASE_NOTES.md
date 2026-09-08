# Google Ads Agents v0.6.1

Release date: 2026-09-08

This release makes installation, supported workflows and example output easier to verify from the repository front page.

## Included

- Rewritten GitHub README with a clear capability table, source installation, quick start, tested commands and links to related tools.
- Project-specific SVG banner and icon, plus a real output screenshot generated from synthetic fixtures.
- Reproducible offline examples, an explicit test section and maintainer release instructions.
- Separated direct CLI apply behavior from the confirmation workflow in agent instructions.
- Documented per-MCC profiles, the 24-hour session and both independent test suites.

## Validation

174 CLI tests and 55 hosted sign-in tests passed (229 total). Ruff passed.

Local validation used Windows and Python 3.12.14 (Node 24 for GTM Diff). The [verification record](VERIFICATION.md) lists the checks and their scope. The repository's CI matrix provides the other supported runtime/OS checks. No live ad account, analytics property, Figma file, AI call or external account write was used for the examples.

## Downloads

Use the source archive for the complete toolkit, including scripts, skills, configuration, documentation and demo fixtures. `SHA256SUMS.txt` records the attached artifact hashes. GitHub's automatically generated source downloads are also available.

Package-registry publishing is separate from this GitHub release and remains controlled by the existing opt-in repository settings. No claim is made that this version is published on PyPI or npm.

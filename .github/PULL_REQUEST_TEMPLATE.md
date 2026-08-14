## What this changes

<!-- One sentence on what changed and why. -->

## How to verify

<!--
ruff check scripts/ hooks/ webapp/
pytest scripts/ -q
pytest webapp/tests/ -q

Add manual smoke-test steps if relevant.
-->

## Checklist

- [ ] `ruff check scripts/ hooks/ webapp/` clean
- [ ] `pytest scripts/ -q` passes
- [ ] `pytest webapp/tests/ -q` passes (if `webapp/` was touched)
- [ ] No new external API calls in tests
- [ ] No credentials, developer tokens, or customer IDs in committed files
- [ ] Any new mutate path shows the operation JSON and waits for `y/N`
- [ ] Google Ads API resource / field / enum names verified against the current reference
- [ ] CHANGELOG.md updated if this is user-visible
- [ ] Docs updated if the user-facing surface changed

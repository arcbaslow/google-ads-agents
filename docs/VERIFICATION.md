# Release verification — v0.6.1

Date: 2026-09-08. Local environment: Windows, Python 3.12.14; Node.js 24 for GTM Diff.

174 CLI tests and 55 hosted sign-in tests passed (229 total). Ruff passed.

| Check | Command | Result |
| --- | --- | --- |
| CLI tests | `python -m pytest scripts/ -q` | Passed |
| Webapp tests | `python -m pytest webapp/tests/ -q` | Passed |
| Ruff | `python -m ruff check scripts/ hooks/ webapp/` | Passed |

## Documentation and examples

- Executed the offline example commands from README against committed synthetic fixtures.
- Captured the generated output in a browser. Screenshots are output previews, not live dashboards.
- Checked local README links, SVG syntax, image presence, release versions and whitespace.
- Built the release artifacts before publishing. Source archives contain only tracked repository files.

## Scope

The test results above are a dated local run, not a claim that every test was run locally on every CI platform. API responses are mocked where tests require them. Live authentication, account mutations, external-service behavior and paid AI calls were not exercised. The CI badge links to the actual workflow rather than a static passing label.

## Build artifacts

Source distribution and wheel built successfully; `twine check` passed. The offline report/extraction example also passed after loading the module from the extracted wheel, outside the repository.

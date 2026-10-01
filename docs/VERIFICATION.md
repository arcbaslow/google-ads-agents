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


# Roadmap branch verification

Date: 2026-09-30. Branch: `roadmap-work`, based on master `1aa6db6`.
Windows, Python 3.12.14, google-ads 33.0.0, Ruff 0.16.9, pytest 9.1.1.
Installed the editable project with its dev extra and webapp/requirements.txt
in a local virtual environment. No release version was changed.

| Check | Baseline | Final |
| --- | --- | --- |
| `ruff check scripts/ hooks/ webapp/` | Passed | Passed |
| `pytest scripts/ -q` | 174 passed | 274 passed |
| `pytest webapp/tests/ -q` | 55 passed | 62 passed |

Both web runs reported the same Starlette warning about deprecated httpx
TestClient integration. No live OAuth, Google Ads request or mutation was run.
Python 3.10, 3.11 and 3.13 and production PostgreSQL were not exercised locally.

## Per-commit checks

All three required checks passed immediately before each commit. The table
records adapter and web test counts; Ruff passed for every row.

| Commit | Change | Adapter tests | Web tests |
| --- | --- | --- | --- |
| `5d3ee11` | Enforce operation review and validation | 210 | 55 |
| `9eda92c` | Block incomplete campaign creation | 215 | 55 |
| `aa4faa7` | Correct brand lookup and reject invalid exclusion writes | 220 | 55 |
| `ca03248` | Construct hosted discovery client correctly | 220 | 56 |
| `3649efa` | Report permanent refresh failures as reconnect required | 220 | 59 |
| `e8e44fe` | Bind sign-in to the initiating browser | 220 | 62 |
| `73aa769` | Select v25 and repair incompatible fields | 240 | 62 |
| `b4fda27` | Align operator instructions | 240 | 62 |
| `54eb00b` | Add Demand Gen reads | 246 | 62 |
| `f65ad48` | Correct age resource and broaden schema checks | 271 | 62 |
| `5947a0e` | Preserve API names in protobuf response JSON | 274 | 62 |
| Roadmap and verification documentation | Record results and deferred work | 274 | 62 |

## Test isolation for this review

The owner's restriction included temporary files with the normal credential
and session filenames, and dotenv reads. Existing fixtures use those names,
so both baseline and final pytest runs used the same external harness. The
harness changed only test fixture paths and settings; it did not change
production authentication or the session hook. It also guarded Python socket
connections. Loopback is allowed for Windows asyncio's internal socket pair.
An initial harness attempt blocked that pair; it was corrected before the
baseline above was recorded.

Save the following to `.venv/audit_tests.py` to reproduce this isolation, then
run `python .venv/audit_tests.py scripts/ -q` and
`python .venv/audit_tests.py webapp/tests/ -q`. These invoke pytest with the
same suite arguments used in CONTRIBUTING.md.

```python
import os
import sys
from pathlib import Path
from unittest.mock import patch
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'webapp'))
sys.path.insert(0, str(ROOT / 'scripts'))
from app.config import Settings
Settings.model_config['env_file'] = None

class Isolation:
    @pytest.hookimpl(hookwrapper=True)
    def pytest_fixture_setup(self, fixturedef, request):
        outcome = yield
        if fixturedef.argname == '_isolate_paths':
            import gads_auth
            gads_auth.CREDENTIALS_PATH = gads_auth.CREDENTIALS_PATH.with_name('test-credentials-store.json')
            gads_auth.SESSION_PATH = gads_auth.SESSION_PATH.with_name('test-session-store.json')
        elif fixturedef.argname == 'hook':
            hook = outcome.get_result()
            if hasattr(hook, 'SESSION_PATH'):
                hook.SESSION_PATH = hook.SESSION_PATH.with_name('test-hook-session.json')

# Fail closed if an unmocked network path is introduced.
import socket
original_connect = socket.socket.connect
def blocked(*args, **kwargs):
    if len(args) > 1 and args[1][0] in ('127.0.0.1', '::1'):
        return original_connect(*args, **kwargs)
    raise AssertionError('Network access is forbidden in this test run')

os.environ['PYTHONUTF8'] = '1'
with patch('socket.socket.connect', blocked), patch('socket.create_connection', blocked):
    raise SystemExit(pytest.main(sys.argv[1:], plugins=[Isolation()]))
```

## Scope after the initial Now pass (historical)

The following records the initial boundary. The continuation section below
supersedes the unavailable-writer, onboarding and concurrency statements.

- Regression tests use mocked services and real local message types where
  schema fidelity matters. Resource/field checks are offline and cannot prove
  a GAQL combination will be accepted for a particular account.
- Browser binding was exercised with independent ASGI TestClient cookie jars,
  not a deployed browser/OAuth flow. Concurrent state consumption still needs
  database-level work, as listed in ROADMAP.md.
- New campaign and brand-exclusion writes are deliberately unavailable. Their
  replacements require complete atomic requests or shared-list management.
- The Cloud project access migration is documented but onboarding remains a
  proposal. No real new-project approval, account eligibility or token
  revocation was tested.
- `scripts/gads_auth.py` and `hooks/session_gate.py` have no diff from master.
  The 24-hour cap, session-gate behavior and release version remain unchanged.
- Changes were committed locally only. Nothing was pushed, tagged or published.

## Roadmap follow-up checks

Continued on `roadmap-work` from `59ca104` using the same isolated harness and
Python environment. The starting checks were Ruff passing, 274 adapter tests
and 62 web tests. All three required checks pass before each follow-up commit.

| Change | Ruff | Adapter tests | Web tests |
| --- | --- | --- | --- |
| Preserve bound providers across both audit worker pools | Pass | 277 | 62 |
| Clear unreadable tokens during hosted disconnect | Pass | 277 | 65 |
| Reject unsupported keyword research locales | Pass | 292 | 65 |

The provider regression tests failed before the fix: worker threads resolved
the default file provider. They now pass with two concurrent callers, each
running two accounts and two adapters. This verifies context isolation with
mock providers, not the thread safety of a shared database session.

Disconnect regression tests failed before the fix for corrupt ciphertext,
an unavailable key version and invalid plaintext encoding. They now verify
local cleanup and repeat disconnection without calling Google revocation.

Keyword tests reproduced silent locale substitution before the fix. They
cover invalid codes before client construction, supported constant mappings,
case normalization, empty results and real v25 response messages with mocked
services. No live keyword request was made.

## Bounded roadmap continuation (2026-10-01)

The prior follow-up was pushed and merged into `master` at the owner's request.
This continuation started from `65ec5a6` on `roadmap-work`: Ruff passed,
292 adapter tests passed and 65 web tests passed. The same Python 3.12
virtual environment and isolated pytest wrapper were used throughout.

Every commit below had all three required checks pass before committing.
Counts include descriptor checks generated from query literals, so changes
in query literals can also change the test count.

| Commit | Change | Ruff | Adapter tests | Web tests |
| --- | --- | --- | --- | --- |
| `e1a8a7d` | Preserve nested and per-entity findings | Pass | 295 | 65 |
| `996c33b` | Consume OAuth state atomically | Pass | 295 | 69 |
| `5f0c3cc` | Redact audit and write provider errors | Pass | 303 | 69 |
| `0c59bc7` | Support Cloud project access without legacy tokens | Pass | 306 | 70 |
| `8515d89` | Add scoped PMax reporting | Pass | 315 | 70 |
| `6b72ab7` | Read Demand Gen and AI Max configuration | Pass | 319 | 70 |
| `0b597a3` | Read upload diagnostics and static consent evidence | Pass | 324 | 70 |
| `0db99d6` | Discover managed accounts with login routing | Pass | 327 | 70 |
| `528725d` | Create PAUSED Search shells atomically | Pass | 342 | 70 |
| `a90e7a0` | Create/reuse and attach PMax brand lists | Pass | 357 | 70 |
| `1cc356e` | Redact read errors and cover remaining baseline adapters | Pass | 387 | 70 |
| `e964993` | Export bounded queries and saved audit snapshots | Pass | 401 | 70 |
| `92e96ef` | Add offline agent safety fixtures | Pass | 406 | 70 |
| `5343a92` | Read migration dates and asset-group tracking settings | Pass | 410 | 70 |
| `5701336` | Redact local auth and history-query failures | Pass | 413 | 70 |
| Completion documentation | Record bounded scope and interoperability | Pass | 413 | 70 |

Final checks are Ruff passing, 413 adapter tests passing and 70 web tests
passing. The existing Starlette httpx integration deprecation warning remains.
An additional coverage run passed all 410 adapter tests: no production
`gads_*.py` module had zero executed lines. Example line coverage: campaign
creation 93%, brands 81%, export 90%, thin channel wrappers 91%, geos 58%.
This is not complete branch coverage or proof of live API compatibility.

The following boundaries were checked separately:

- `enforce_session()` has an identical AST to `65ec5a6`; the session gate hook
  has no diff. Version metadata remains 0.6.1. Other auth code changed for
  optional legacy tokens and redacted authentication diagnostics.
- New modules are registered in `pyproject.toml`. `git diff --check` passes.
- Tests used mocked services, local v25 protobufs and synthetic fixture data.
  No live Ads calls, OAuth exchanges or notification messages were sent.
  Protected credential/session/secret filenames were neither read nor created
  nor staged; test paths were redirected by the isolation wrapper.
- OAuth replay tests use separate SQLite connections. PostgreSQL concurrency,
  deployed browser OAuth, new-project approval and real account permissions
  remain unverified.
- Server-side GAQL combinations, catalogue eligibility, campaign creation and
  mutate validation have not been tested against live accounts. Local checks
  confirm request shape and call sequencing only. Unknown apply outcomes
  require account inspection, not automatic retries.
- Static HTML consent evidence does not verify runtime consent or delivery.
  Monitoring exports describe saved snapshots and need external freshness
  checks. Agent task fixtures verify adapter contracts; no language-model
  runtime or upstream MCP server was evaluated.
- The work stays in the existing flat adapters. No hosted audit endpoint,
  dashboard, new MCP service, paid dependency, version bump or release was added.
  Continuation commits are local on `roadmap-work`; no continuation push or
  merge was performed.

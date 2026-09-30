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

## Scope and remaining uncertainty

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

# Auth Backends + Bring-Your-Own OAuth Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a restricted-Google-Workspace user authenticate with their own OAuth client instead of gcloud ADC, behind a pluggable auth-backend abstraction with web-ready storage/refresh seams.

**Architecture:** Credential resolution dispatches on a per-profile `auth_method`. `GcloudAdcBackend` keeps the existing `google.auth.default()` path as the default; `OAuthClientBackend` builds and refreshes `google.oauth2.credentials.Credentials` from a stored refresh token. A `TokenStore` interface (today: `LocalFileTokenStore` over the existing credentials file) isolates token material so the future web app can swap in a DB store without touching backends or `gads_client`.

**Tech Stack:** Python 3.10+, `google-ads`, `google-auth`, `google-auth-oauthlib` (new), pytest.

**Spec:** `docs/superpowers/specs/2026-05-29-auth-backends-design.md`

**Conventions (read before committing):**
- Tests live in `scripts/` as `test_*.py`; run with `cd scripts && python -m pytest -q`. `scripts/conftest.py` autouse-isolates `CREDENTIALS_PATH`/`SESSION_PATH` to a temp dir, so tests touch no real credentials.
- Commit messages: short imperative sentence, sentence case OK. **No** `feat:`/`fix:`/`chore:` prefixes, **no** `Co-Authored-By`, **no** generated-with footer (per `CLAUDE.md`).
- Comments only where the *why* is non-obvious.

---

### Task 1: Add the google-auth-oauthlib dependency

**Files:**
- Modify: `scripts/requirements.txt`
- Modify: `pyproject.toml:8-11`

- [ ] **Step 1: Add the runtime dependency to requirements.txt**

Final content of `scripts/requirements.txt`:

```
google-ads>=25.0.0
google-auth>=2.30.0
google-auth-oauthlib>=1.2.0
```

- [ ] **Step 2: Add the same dependency to pyproject.toml**

In `pyproject.toml`, change the `dependencies` list under `[project]` to:

```toml
dependencies = [
    "google-ads>=25.0.0",
    "google-auth>=2.30.0",
    "google-auth-oauthlib>=1.2.0",
]
```

- [ ] **Step 3: Install it into the active environment**

Run: `pip install "google-auth-oauthlib>=1.2.0"`
Expected: installs `google-auth-oauthlib` and its `requests-oauthlib` dependency, or reports "Requirement already satisfied".

- [ ] **Step 4: Verify the import resolves**

Run: `python -c "import google_auth_oauthlib.flow; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 5: Commit**

```bash
git add scripts/requirements.txt pyproject.toml
git commit -m "add google-auth-oauthlib dependency for the OAuth client flow"
```

---

### Task 2: Token store seam

**Files:**
- Create: `scripts/gads_tokenstore.py`
- Test: `scripts/test_gads_tokenstore.py`

The store reads and writes only the OAuth fields (`client_id`, `client_secret`, `refresh_token`) inside a named profile of the existing credentials file. It reuses `gads_auth`'s profile read/write so there is a single source of truth, and `get` returns `None` unless a refresh token is present.

- [ ] **Step 1: Write the failing test**

Create `scripts/test_gads_tokenstore.py`:

```python
"""LocalFileTokenStore round-trips OAuth material inside a profile. No live API."""

from __future__ import annotations

import gads_auth
from gads_tokenstore import LocalFileTokenStore


def test_get_returns_none_when_no_profile():
    store = LocalFileTokenStore()
    assert store.get("missing") is None


def test_get_returns_none_without_refresh_token():
    gads_auth.add_profile("acme", "DEV", "1")
    store = LocalFileTokenStore()
    assert store.get("acme") is None


def test_set_then_get_round_trips():
    gads_auth.add_profile("acme", "DEV", "1")
    store = LocalFileTokenStore()
    store.set("acme", {
        "client_id": "cid",
        "client_secret": "secret",
        "refresh_token": "rtok",
    })
    rec = store.get("acme")
    assert rec == {"client_id": "cid", "client_secret": "secret", "refresh_token": "rtok"}


def test_set_preserves_existing_profile_fields():
    gads_auth.add_profile("acme", "DEV", "1234567890")
    store = LocalFileTokenStore()
    store.set("acme", {"client_id": "cid", "client_secret": "s", "refresh_token": "r"})
    # developer token and login id survive the token write
    assert gads_auth.get_developer_token() == "DEV"
    assert gads_auth.get_login_customer_id() == "1234567890"


def test_set_creates_profile_when_absent():
    store = LocalFileTokenStore()
    store.set("fresh", {"client_id": "c", "client_secret": "s", "refresh_token": "r"})
    assert store.get("fresh")["refresh_token"] == "r"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd scripts && python -m pytest test_gads_tokenstore.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'gads_tokenstore'`.

- [ ] **Step 3: Write minimal implementation**

Create `scripts/gads_tokenstore.py`:

```python
"""Token storage seam.

LocalFileTokenStore keeps OAuth material inside the existing credentials file
(behind this interface). The future web app implements a DbTokenStore keyed by
user id with the same get/set contract, so auth backends and gads_client need
no change.
"""

from __future__ import annotations

from typing import Any, Protocol

import gads_auth

_OAUTH_FIELDS = ("client_id", "client_secret", "refresh_token")


class TokenStore(Protocol):
    def get(self, key: str) -> dict[str, Any] | None: ...
    def set(self, key: str, record: dict[str, Any]) -> None: ...


class LocalFileTokenStore:
    """OAuth material lives inside the profile named `key`, file mode 0600."""

    def get(self, key: str) -> dict[str, Any] | None:
        prof = gads_auth._profiles().get("profiles", {}).get(key)
        if not prof or not prof.get("refresh_token"):
            return None
        return {f: prof.get(f) for f in _OAUTH_FIELDS}

    def set(self, key: str, record: dict[str, Any]) -> None:
        data = gads_auth._profiles()
        prof = data.setdefault("profiles", {}).setdefault(key, {})
        for f in _OAUTH_FIELDS:
            if f in record:
                prof[f] = record[f]
        gads_auth.save_credentials(data)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd scripts && python -m pytest test_gads_tokenstore.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/gads_tokenstore.py scripts/test_gads_tokenstore.py
git commit -m "add LocalFileTokenStore seam for OAuth material"
```

---

### Task 3: Auth backends

**Files:**
- Create: `scripts/gads_authflow.py`
- Test: `scripts/test_gads_authflow.py`

Defines `AuthBackend`, the two implementations, and `select_backend`, which picks a backend from a profile's `auth_method` and pulls the OAuth record from the token store.

- [ ] **Step 1: Write the failing test**

Create `scripts/test_gads_authflow.py`:

```python
"""Auth backend selection and OAuth credential construction. No live API."""

from __future__ import annotations

import sys
import types

import pytest

import gads_auth
import gads_authflow


class _FakeStore:
    def __init__(self, rec):
        self._rec = rec

    def get(self, key):
        return self._rec

    def set(self, key, record):
        self._rec = record


def test_default_profile_selects_gcloud_backend():
    backend = gads_authflow.select_backend("acme", {})
    assert isinstance(backend, gads_authflow.GcloudAdcBackend)


def test_explicit_gcloud_method_selects_gcloud_backend():
    backend = gads_authflow.select_backend("acme", {"auth_method": "gcloud_adc"})
    assert isinstance(backend, gads_authflow.GcloudAdcBackend)


def test_oauth_method_selects_oauth_backend():
    store = _FakeStore({"client_id": "c", "client_secret": "s", "refresh_token": "r"})
    backend = gads_authflow.select_backend(
        "widgets", {"auth_method": "oauth_client"}, store=store
    )
    assert isinstance(backend, gads_authflow.OAuthClientBackend)


def test_oauth_method_without_token_raises():
    store = _FakeStore(None)
    with pytest.raises(gads_auth.AuthRequiredError):
        gads_authflow.select_backend(
            "widgets", {"auth_method": "oauth_client"}, store=store
        )


def test_oauth_backend_builds_and_refreshes_credentials(monkeypatch):
    """OAuthClientBackend constructs Credentials from the record and refreshes."""
    built = {}
    refreshed = {"called": False}

    class FakeCredentials:
        def __init__(self, **kwargs):
            built.update(kwargs)

        def refresh(self, request):
            refreshed["called"] = True

    # Stub google.oauth2.credentials.Credentials and the transport Request.
    oauth2 = types.ModuleType("google.oauth2")
    creds_mod = types.ModuleType("google.oauth2.credentials")
    creds_mod.Credentials = FakeCredentials
    transport = types.ModuleType("google.auth.transport")
    requests_mod = types.ModuleType("google.auth.transport.requests")
    requests_mod.Request = lambda: object()
    monkeypatch.setitem(sys.modules, "google.oauth2", oauth2)
    monkeypatch.setitem(sys.modules, "google.oauth2.credentials", creds_mod)
    monkeypatch.setitem(sys.modules, "google.auth.transport", transport)
    monkeypatch.setitem(sys.modules, "google.auth.transport.requests", requests_mod)

    backend = gads_authflow.OAuthClientBackend(
        {"client_id": "cid", "client_secret": "sec", "refresh_token": "rtok"}
    )
    backend.credentials()

    assert built["refresh_token"] == "rtok"
    assert built["client_id"] == "cid"
    assert built["client_secret"] == "sec"
    assert built["scopes"] == [gads_auth.ADWORDS]
    assert refreshed["called"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd scripts && python -m pytest test_gads_authflow.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'gads_authflow'`.

- [ ] **Step 3: Write minimal implementation**

Create `scripts/gads_authflow.py`:

```python
"""Auth backends.

Credential resolution dispatches on a profile's auth_method so a restricted
Workspace user can use their own OAuth client instead of gcloud ADC. Every
downstream script is unaffected: gads_client.build_client() calls
gads_auth.get_credentials(), which routes here.
"""

from __future__ import annotations

from typing import Any, Protocol

import gads_auth

TOKEN_URI = "https://oauth2.googleapis.com/token"


class AuthBackend(Protocol):
    def credentials(self) -> Any: ...


class GcloudAdcBackend:
    """The original path: gcloud Application Default Credentials."""

    def credentials(self) -> Any:
        import google.auth

        creds, _project = google.auth.default(scopes=[gads_auth.ADWORDS])
        return creds


class OAuthClientBackend:
    """User-owned OAuth client: build Credentials from a stored refresh token."""

    def __init__(self, record: dict[str, Any]):
        self._record = record

    def credentials(self) -> Any:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        creds = Credentials(
            token=None,
            refresh_token=self._record["refresh_token"],
            client_id=self._record["client_id"],
            client_secret=self._record["client_secret"],
            token_uri=TOKEN_URI,
            scopes=[gads_auth.ADWORDS],
        )
        creds.refresh(Request())
        return creds


def select_backend(profile_name: str | None, profile: dict[str, Any], store=None) -> AuthBackend:
    method = (profile or {}).get("auth_method", "gcloud_adc")
    if method == "oauth_client":
        if store is None:
            from gads_tokenstore import LocalFileTokenStore

            store = LocalFileTokenStore()
        record = store.get(profile_name)
        if not record:
            raise gads_auth.AuthRequiredError(
                f"Profile '{profile_name}' uses oauth_client but has no stored "
                f"refresh token. Run:\n  python scripts/gads_auth.py --oauth-login "
                f"--client-secrets client_secret.json"
            )
        return OAuthClientBackend(record)
    return GcloudAdcBackend()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd scripts && python -m pytest test_gads_authflow.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/gads_authflow.py scripts/test_gads_authflow.py
git commit -m "add gcloud and oauth-client auth backends with selection"
```

---

### Task 4: Profile schema — auth_method and OAuth setters

**Files:**
- Modify: `scripts/gads_auth.py` (add `set_auth_method`, `set_oauth_credentials`; default `auth_method` on read)
- Test: `scripts/test_gads_auth.py` (append cases)

`auth_method` is resolved with `.get("auth_method", "gcloud_adc")` so old/migrated profiles need no rewrite. New helpers persist the OAuth method and material.

- [ ] **Step 1: Write the failing tests**

Append to `scripts/test_gads_auth.py`:

```python
def test_migrated_profile_defaults_to_gcloud_method():
    gads_auth.add_profile("acme", "DEV", "1")
    assert gads_auth.active_profile().get("auth_method", "gcloud_adc") == "gcloud_adc"


def test_set_auth_method_persists():
    gads_auth.add_profile("acme", "DEV", "1")
    gads_auth.set_auth_method("acme", "oauth_client")
    assert gads_auth.active_profile()["auth_method"] == "oauth_client"


def test_set_oauth_credentials_sets_method_and_fields():
    gads_auth.add_profile("acme", "DEV", "1")
    gads_auth.set_oauth_credentials("acme", "cid", "sec", "rtok")
    prof = gads_auth.active_profile()
    assert prof["auth_method"] == "oauth_client"
    assert prof["client_id"] == "cid"
    assert prof["client_secret"] == "sec"
    assert prof["refresh_token"] == "rtok"


def test_set_oauth_credentials_creates_and_activates_profile():
    gads_auth.set_oauth_credentials("fresh", "cid", "sec", "rtok")
    assert gads_auth.active_profile_name() == "fresh"
    assert gads_auth.active_profile()["refresh_token"] == "rtok"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd scripts && python -m pytest test_gads_auth.py -q -k "auth_method or oauth_credentials"`
Expected: FAIL with `AttributeError: module 'gads_auth' has no attribute 'set_auth_method'`.

- [ ] **Step 3: Write minimal implementation**

In `scripts/gads_auth.py`, add these two functions immediately after `set_login_customer_id` (around line 279, before the `# ---------- CLI ----------` banner):

```python
def set_auth_method(name: str, method: str) -> None:
    data = _profiles()
    data.setdefault("profiles", {}).setdefault(name, {})["auth_method"] = method
    if not data.get("active"):
        data["active"] = name
    save_credentials(data)


def set_oauth_credentials(
    name: str, client_id: str, client_secret: str, refresh_token: str
) -> None:
    """Persist OAuth client material and flip the profile to oauth_client."""
    from gads_tokenstore import LocalFileTokenStore

    LocalFileTokenStore().set(name, {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    })
    set_auth_method(name, "oauth_client")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd scripts && python -m pytest test_gads_auth.py -q -k "auth_method or oauth_credentials"`
Expected: PASS (4 passed).

- [ ] **Step 5: Run the full auth test file to confirm no regressions**

Run: `cd scripts && python -m pytest test_gads_auth.py -q`
Expected: PASS (all existing tests plus the 4 new ones).

- [ ] **Step 6: Commit**

```bash
git add scripts/gads_auth.py scripts/test_gads_auth.py
git commit -m "store auth_method and oauth material on profiles"
```

---

### Task 5: Route get_credentials through the backend

**Files:**
- Modify: `scripts/gads_auth.py:126-146` (replace the body of `get_credentials`)
- Test: `scripts/test_gads_auth.py` (append cases)

`get_credentials` keeps enforcing the 24h session, then dispatches to the selected backend. The error hint adapts to the active profile's method.

- [ ] **Step 1: Write the failing tests**

Append to `scripts/test_gads_auth.py`:

```python
def test_get_credentials_uses_selected_backend(monkeypatch):
    """get_credentials dispatches to the backend chosen for the active profile."""
    import gads_authflow

    gads_auth.add_profile("acme", "DEV", "1")
    gads_auth.session_start()

    sentinel = object()

    class FakeBackend:
        def credentials(self):
            return sentinel

    monkeypatch.setattr(gads_authflow, "select_backend", lambda name, prof, **kw: FakeBackend())
    assert gads_auth.get_credentials() is sentinel


def test_get_credentials_expired_session_raises(monkeypatch):
    from datetime import datetime, timedelta, timezone

    gads_auth.add_profile("acme", "DEV", "1")
    expired = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    gads_auth.SESSION_PATH.write_text('{"started_at": "%s"}' % expired)
    with pytest.raises(gads_auth.SessionExpiredError):
        gads_auth.get_credentials()


def test_get_credentials_backend_failure_wraps_as_auth_required(monkeypatch):
    import gads_authflow

    gads_auth.add_profile("acme", "DEV", "1")
    gads_auth.session_start()

    class FailingBackend:
        def credentials(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(gads_authflow, "select_backend", lambda name, prof, **kw: FailingBackend())
    with pytest.raises(gads_auth.AuthRequiredError):
        gads_auth.get_credentials()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd scripts && python -m pytest test_gads_auth.py -q -k "get_credentials"`
Expected: FAIL — the current `get_credentials` calls `google.auth.default()` directly and ignores `select_backend`, so `test_get_credentials_uses_selected_backend` fails (returns real creds attempt / error, not the sentinel).

- [ ] **Step 3: Write the implementation**

In `scripts/gads_auth.py`, replace the entire `get_credentials` function (currently lines 126-146) with:

```python
def get_credentials():
    """Resolve credentials for the active profile's backend, after the 24h cap.

    gcloud_adc profiles use google.auth.default(); oauth_client profiles build
    Credentials from a stored refresh token. Selection lives in gads_authflow.
    """
    enforce_session()
    import gads_authflow

    name = active_profile_name()
    profile = active_profile()
    backend = gads_authflow.select_backend(name, profile)
    try:
        return backend.credentials()
    except AuthRequiredError:
        raise
    except Exception as e:
        method = (profile or {}).get("auth_method", "gcloud_adc")
        if method == "oauth_client":
            hint = (
                f"OAuth client credentials for profile '{name}' failed to refresh "
                f"({e}). Re-run:\n  python scripts/gads_auth.py --oauth-login "
                f"--client-secrets client_secret.json"
            )
        else:
            hint = f"No application default credentials found ({e}).\nRun:\n  {adc_command()}"
        raise AuthRequiredError(hint) from e
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd scripts && python -m pytest test_gads_auth.py -q -k "get_credentials"`
Expected: PASS (3 passed).

- [ ] **Step 5: Run the full auth + authflow test files**

Run: `cd scripts && python -m pytest test_gads_auth.py test_gads_authflow.py -q`
Expected: PASS (all green).

- [ ] **Step 6: Commit**

```bash
git add scripts/gads_auth.py scripts/test_gads_auth.py
git commit -m "route get_credentials through the selected auth backend"
```

---

### Task 6: --oauth-login and --set-oauth CLI commands

**Files:**
- Modify: `scripts/gads_auth.py` (add `cmd_oauth_login`, `cmd_set_oauth`, argparse flags, dispatch)
- Test: `scripts/test_gads_auth.py` (append cases)

`--oauth-login` runs the loopback browser flow (mocked in tests) and persists the result. `--set-oauth` is the manual fallback for a pre-obtained refresh token. Both end on `set_oauth_credentials` + `session_start`.

- [ ] **Step 1: Write the failing tests**

Append to `scripts/test_gads_auth.py`:

```python
def test_oauth_login_persists_token_and_starts_session(monkeypatch):
    """--oauth-login runs the (mocked) flow and stores the refresh token."""
    import google_auth_oauthlib.flow as flow_mod

    class FakeCreds:
        client_id = "cid"
        client_secret = "sec"
        refresh_token = "rtok"

    class FakeFlow:
        def run_local_server(self, **kwargs):
            return FakeCreds()

    monkeypatch.setattr(
        flow_mod.InstalledAppFlow,
        "from_client_secrets_file",
        classmethod(lambda cls, path, scopes: FakeFlow()),
    )

    args = _ns(
        oauth_login=True,
        client_secrets="client_secret.json",
        add_profile="acme",
        developer_token="DEV",
        login_customer_id="1234567890",
        no_browser=False,
    )
    assert gads_auth.cmd_oauth_login(args) == 0

    prof = gads_auth.active_profile()
    assert gads_auth.active_profile_name() == "acme"
    assert prof["auth_method"] == "oauth_client"
    assert prof["refresh_token"] == "rtok"
    assert gads_auth.get_developer_token() == "DEV"
    assert gads_auth.session_status()["valid"] is True


def test_oauth_login_requires_existing_or_new_profile(monkeypatch):
    args = _ns(
        oauth_login=True,
        client_secrets="client_secret.json",
        add_profile=None,
        developer_token=None,
        login_customer_id=None,
        no_browser=False,
    )
    # No active profile and no --add-profile: refuse before touching the flow.
    assert gads_auth.cmd_oauth_login(args) == 2


def test_set_oauth_manual_fallback(monkeypatch):
    gads_auth.add_profile("acme", "DEV", "1")
    args = _ns(
        set_oauth="acme",
        client_id="cid",
        client_secret="sec",
        refresh_token="rtok",
    )
    assert gads_auth.cmd_set_oauth(args) == 0
    prof = gads_auth.active_profile()
    assert prof["auth_method"] == "oauth_client"
    assert prof["refresh_token"] == "rtok"
```

Also add this tiny namespace helper near the top of `scripts/test_gads_auth.py` (after the imports):

```python
def _ns(**kwargs):
    import argparse
    return argparse.Namespace(**kwargs)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd scripts && python -m pytest test_gads_auth.py -q -k "oauth_login or set_oauth"`
Expected: FAIL with `AttributeError: module 'gads_auth' has no attribute 'cmd_oauth_login'`.

- [ ] **Step 3: Write the command implementations**

In `scripts/gads_auth.py`, add these two command functions just before the `# ---------- CLI ----------` `main` function (after `cmd_list_profiles`, around line 372):

```python
def cmd_oauth_login(args) -> int:
    name = args.add_profile or active_profile_name()
    if not name:
        print(json.dumps({
            "error": "no profile. Pass --add-profile NAME --developer-token TOKEN, "
                     "or select an existing profile with --use-profile first."
        }, indent=2))
        return 2
    if args.add_profile:
        if not args.developer_token:
            print(json.dumps(
                {"error": "--developer-token is required with --add-profile"}, indent=2
            ))
            return 2
        add_profile(args.add_profile, args.developer_token, args.login_customer_id)

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(args.client_secrets, scopes=[ADWORDS])
    creds = flow.run_local_server(port=0, open_browser=not args.no_browser)
    set_oauth_credentials(name, creds.client_id, creds.client_secret, creds.refresh_token)
    session_start()
    print(json.dumps({
        "profile": name,
        "auth_method": "oauth_client",
        "refresh_token": "set",
        "session": session_status(),
    }, indent=2))
    return 0


def cmd_set_oauth(args) -> int:
    """Manual fallback: store a pre-obtained client id/secret/refresh token."""
    if not (args.client_id and args.client_secret and args.refresh_token):
        print(json.dumps({
            "error": "--set-oauth needs --client-id, --client-secret, --refresh-token"
        }, indent=2))
        return 2
    set_oauth_credentials(args.set_oauth, args.client_id, args.client_secret, args.refresh_token)
    session_start()
    print(json.dumps({
        "profile": args.set_oauth,
        "auth_method": "oauth_client",
        "refresh_token": "set",
    }, indent=2))
    return 0
```

- [ ] **Step 4: Wire the argparse flags and dispatch**

In `scripts/gads_auth.py` `main()`, add these arguments alongside the existing ones (after the `--set-login-customer-id` line, around line 386):

```python
    p.add_argument("--oauth-login", action="store_true",
                   help="run the OAuth loopback flow with your own client")
    p.add_argument("--client-secrets", metavar="PATH",
                   help="client_secret.json from your Desktop OAuth client")
    p.add_argument("--no-browser", action="store_true",
                   help="print the URL instead of opening a browser")
    p.add_argument("--set-oauth", metavar="NAME",
                   help="manual fallback: set OAuth material on a profile")
    p.add_argument("--client-id", metavar="ID", help="paired with --set-oauth")
    p.add_argument("--client-secret", metavar="SECRET", help="paired with --set-oauth")
    p.add_argument("--refresh-token", metavar="TOKEN", help="paired with --set-oauth")
```

Then add dispatch branches in `main()` before the `if args.customers:` branch (around line 407):

```python
    if args.oauth_login:
        return cmd_oauth_login(args)
    if args.set_oauth:
        return cmd_set_oauth(args)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd scripts && python -m pytest test_gads_auth.py -q -k "oauth_login or set_oauth"`
Expected: PASS (3 passed).

- [ ] **Step 6: Run the full suite to confirm no regressions**

Run: `cd scripts && python -m pytest -q`
Expected: PASS — the full suite (previously 132 tests) plus the new cases, all green.

- [ ] **Step 7: Commit**

```bash
git add scripts/gads_auth.py scripts/test_gads_auth.py
git commit -m "add oauth-login loopback flow and set-oauth manual fallback"
```

---

### Task 7: Documentation

**Files:**
- Modify: `docs/SETUP.md` (add "Option B" auth path; note web-app trajectory)
- Modify: `README.md:49-86` (Authenticate section: pointer to Option B)

No tests. Documentation must match the implemented flags exactly (`--oauth-login`, `--client-secrets`, `--no-browser`, `--set-oauth`).

- [ ] **Step 1: Add the Option B section to SETUP.md**

In `docs/SETUP.md`, replace the `## 3. Sign in` heading and its body with a two-option structure. The new `## 3. Sign in` section reads:

```markdown
## 3. Sign in

Two ways to authenticate. Pick one per profile.

### Option A — gcloud (default)

From the project directory:

\```
python scripts/gads_auth.py --adc
\```

It prints the exact `gcloud auth application-default login --scopes=...`
command. Run it. A browser opens, sign in, grant access.

### Option B — your own OAuth client (restricted Google Workspace)

If your Workspace admin blocks the gcloud sign-in ("Access blocked: this app
is blocked"), use your own OAuth client. It does not depend on the gcloud app
and needs no admin help.

1. Create a Google Cloud project in your Workspace org
   (https://console.cloud.google.com/projectcreate).
2. APIs & Services -> OAuth consent screen -> User type **Internal**.
   Internal apps skip Google verification for the restricted `adwords`
   scope and are not subject to the org's third-party-app block.
3. APIs & Services -> Credentials -> Create credentials -> OAuth client ID ->
   Application type **Desktop app**. Download the JSON as
   `client_secret.json`.
4. Run the loopback flow:

\```
python scripts/gads_auth.py --oauth-login \
    --client-secrets client_secret.json \
    --add-profile acme --developer-token <TOKEN> --login-customer-id <MCC>
\```

A browser opens on a localhost port; sign in and grant access. The refresh
token is stored in the profile (file mode 0600) and the 24h session starts.
On a headless machine add `--no-browser` to print the URL instead.

If even creating a Cloud project is blocked, obtain a refresh token with your
client elsewhere and paste it:

\```
python scripts/gads_auth.py --set-oauth acme \
    --client-id <ID> --client-secret <SECRET> --refresh-token <TOKEN>
\```

> Web-app trajectory: the same flow becomes a **Web** OAuth client with a
> redirect URI, the refresh/exchange code is reused, and a database token
> store replaces the local file. See
> `docs/superpowers/specs/2026-05-29-auth-backends-design.md`.
```

(Note: in the real file, write the fenced code blocks with normal triple
backticks — the `\``` above is only escaped for this plan document.)

- [ ] **Step 2: Renumber the rest of SETUP.md if needed**

Confirm the sections after "Sign in" ("Configure local credentials", "Verify", etc.) still read correctly. The "Configure local credentials" step (`--add-profile`) still applies to Option A; for Option B the profile is created inline by `--oauth-login`. Add one sentence at the top of "## 4. Configure local credentials": `Option B users who passed --add-profile to --oauth-login already have a profile and can skip to Verify.`

- [ ] **Step 3: Add a pointer in the README Authenticate section**

In `README.md`, in the "Authenticate" section, after the paragraph ending `...stays on it.` (the migration note around line 75), add:

```markdown
If your Google Workspace blocks the gcloud sign-in, authenticate with your
own OAuth client instead — no admin needed. See "Option B" in
[docs/SETUP.md](docs/SETUP.md).
```

- [ ] **Step 4: Verify the docs reference only real flags**

Run: `cd scripts && python gads_auth.py --help`
Expected: the help output lists `--oauth-login`, `--client-secrets`, `--no-browser`, `--set-oauth`, `--client-id`, `--client-secret`, `--refresh-token`. Confirm the commands quoted in the docs match.

- [ ] **Step 5: Commit**

```bash
git add docs/SETUP.md README.md
git commit -m "document the OAuth client auth path for restricted Workspaces"
```

---

## Final verification

- [ ] **Run the whole suite**

Run: `cd scripts && python -m pytest -q`
Expected: all tests pass (132 prior + ~19 new).

- [ ] **Lint**

Run: `python -m ruff check scripts`
Expected: no errors (or only pre-existing ones unrelated to these files).

- [ ] **Sanity-check the CLI help**

Run: `cd scripts && python gads_auth.py --help`
Expected: new flags present; no traceback.

---

## Self-review notes (author)

- **Spec coverage:** auth backends (Task 3), profile `auth_method` (Task 4), token-store seam (Task 2), `get_credentials` dispatch (Task 5), `--oauth-login` loopback + `--no-browser` + manual fallback (Task 6), dependency (Task 1), SETUP Option B + README pointer + web-app note (Task 7). 24h session cap is preserved (Task 5 enforces it; Task 6 starts it). Out-of-scope items (web server, DB store, centralized dev token, SA/DWD) are intentionally absent.
- **Type/name consistency:** `select_backend(profile_name, profile, store=None)`, `OAuthClientBackend(record)`, `TokenStore.get/set`, `set_auth_method`, `set_oauth_credentials(name, client_id, client_secret, refresh_token)`, and the CLI flag names are used identically across tasks 2-7.
- **No placeholders:** every code and test step shows full content; commands list expected output.
```

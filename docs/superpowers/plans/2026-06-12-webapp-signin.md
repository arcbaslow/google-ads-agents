# Web App Sign-In Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `X-Dev-User` identity stub with Google Sign-In (OIDC) and DB-backed 24h sessions, per `docs/superpowers/specs/2026-06-12-webapp-signin-design.md`.

**Architecture:** Sign-in reuses the existing PKCE / state / ID-token helpers in `webapp/app/oauth.py` with identity-only scopes. Opaque session tokens (sha256-hashed at rest) live in a new `sessions` table and travel in an HttpOnly `gads_session` cookie. `get_current_user` resolves the cookie and 401s otherwise; a global same-origin dependency rejects cross-origin unsafe methods.

**Tech Stack:** FastAPI, SQLAlchemy 2 (SQLite in tests), pydantic-settings, pytest. No new dependencies.

**Conventions:** Run tests with `python -m pytest <path> -q` from the repo root. Commit messages: short imperative sentence, no prefixes, no trailers (CLAUDE.md). TDD throughout: watch each new test fail before implementing.

---

### Task 1: Sign-in settings

**Files:**
- Modify: `webapp/app/config.py`
- Modify: `webapp/tests/test_config.py`
- Modify: `webapp/tests/conftest.py` (settings fixture)
- Modify: `webapp/tests/test_api.py` (`_settings` helper)

- [ ] **Step 1: Write the failing test** — in `webapp/tests/test_config.py`, add `SIGNIN_REDIRECT_URI` to `_env` and assert the new fields:

```python
def _env(**over):
    base = dict(
        DATABASE_URL="sqlite://",
        FERNET_KEYS=f'["{Fernet.generate_key().decode()}"]',
        GOOGLE_OAUTH_CLIENT_ID="cid",
        GOOGLE_OAUTH_CLIENT_SECRET="secret",
        GOOGLE_DEVELOPER_TOKEN="dev",
        OAUTH_REDIRECT_URI="http://localhost:8000/oauth/google/callback",
        SIGNIN_REDIRECT_URI="http://localhost:8000/auth/google/callback",
    )
    base.update(over)
    return base
```

In `test_settings_load_from_env`, add:

```python
    assert s.signin_redirect_uri == "http://localhost:8000/auth/google/callback"
    assert s.allowed_signins == []
    assert s.session_max_hours == 24
    assert s.cookie_secure is True
```

In `test_missing_required_raises`, add `"SIGNIN_REDIRECT_URI"` to the `delenv` tuple.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest webapp/tests/test_config.py -q`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'signin_redirect_uri'` (or pydantic ValidationError).

- [ ] **Step 3: Implement** — in `webapp/app/config.py`, add fields after `oauth_redirect_uri` (keep `dev_user_id` for now; it is removed in Task 9):

```python
    oauth_redirect_uri: str
    signin_redirect_uri: str
    allowed_signins: list[str] = []     # email domains or full emails; empty = anyone
    session_max_hours: int = 24
    cookie_secure: bool = True
    dev_user_id: str = "dev"
```

`signin_redirect_uri` is required, so every test `Settings(...)` construction needs it. In `webapp/tests/conftest.py` `settings` fixture and `webapp/tests/test_api.py` `_settings()`, add:

```python
        signin_redirect_uri="http://localhost:8000/auth/google/callback",
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest webapp/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add webapp/app/config.py webapp/tests/test_config.py webapp/tests/conftest.py webapp/tests/test_api.py
git commit -m "add sign-in settings"
```

---

### Task 2: Session model, google_sub, state purpose

**Files:**
- Modify: `webapp/app/models.py`
- Modify: `webapp/tests/test_models.py`

- [ ] **Step 1: Write the failing tests** — replace the imports at the top of `webapp/tests/test_models.py` and append three tests:

```python
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Connection, OAuthState, User, UserSession
```

```python
def test_user_session_roundtrip(session):
    u = User(email="s@example.com")
    session.add(u)
    session.flush()
    row = UserSession(user_id=u.id, token_hash="ab" * 32,
                      expires_at=datetime.now(timezone.utc))
    session.add(row)
    session.flush()
    got = session.get(UserSession, row.id)
    assert got.user_id == u.id
    assert got.created_at is not None


def test_user_google_sub_unique(session):
    session.add(User(google_sub="sub-1"))
    session.commit()
    session.add(User(google_sub="sub-1"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_oauth_state_allows_null_user_and_defaults_purpose(session):
    row = OAuthState(state="s1", user_id=None, code_verifier="v",
                     expires_at=datetime.now(timezone.utc))
    session.add(row)
    session.commit()
    assert row.purpose == "connect"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest webapp/tests/test_models.py -q`
Expected: FAIL — `ImportError: cannot import name 'UserSession'`.

- [ ] **Step 3: Implement** — in `webapp/app/models.py`:

To `User`, after `email`:

```python
    google_sub: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
```

In `OAuthState`, make `user_id` nullable and add `purpose`:

```python
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), index=True, nullable=True
    )
    purpose: Mapped[str] = mapped_column(String(16), default="connect")
```

New model after `OAuthState`:

```python
class UserSession(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest webapp/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add webapp/app/models.py webapp/tests/test_models.py
git commit -m "add session model, google sub, and oauth state purpose"
```

---

### Task 3: Session helpers

**Files:**
- Create: `webapp/app/sessions.py`
- Create: `webapp/tests/test_sessions.py`

- [ ] **Step 1: Write the failing tests** — create `webapp/tests/test_sessions.py`:

```python
from datetime import datetime, timedelta, timezone

from app import sessions
from app.models import User, UserSession


def _user(session):
    u = User(email="s@example.com")
    session.add(u)
    session.commit()
    return u


def test_create_and_resolve_roundtrip(session):
    u = _user(session)
    token, row = sessions.create_session(session, u.id, max_hours=24)
    assert row.token_hash != token            # only the hash is stored
    got = sessions.resolve_session(session, token)
    assert got is not None
    assert got.user_id == u.id


def test_resolve_unknown_token_returns_none(session):
    assert sessions.resolve_session(session, "nope") is None


def test_resolve_expired_session_deletes_row(session):
    u = _user(session)
    token, row = sessions.create_session(session, u.id, max_hours=24)
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    session.commit()
    assert sessions.resolve_session(session, token) is None
    assert session.query(UserSession).count() == 0


def test_delete_session(session):
    u = _user(session)
    token, _ = sessions.create_session(session, u.id, max_hours=24)
    sessions.delete_session(session, token)
    assert sessions.resolve_session(session, token) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest webapp/tests/test_sessions.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.sessions'`.

- [ ] **Step 3: Implement** — create `webapp/app/sessions.py`:

```python
"""DB-backed sessions: opaque tokens, sha256 at rest, absolute expiry."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import UserSession


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user_id: str, max_hours: int) -> tuple[str, UserSession]:
    token = secrets.token_urlsafe(32)
    row = UserSession(
        user_id=user_id,
        token_hash=_hash(token),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=max_hours),
    )
    db.add(row)
    db.commit()
    return token, row


def resolve_session(db: Session, token: str) -> UserSession | None:
    row = db.query(UserSession).filter(UserSession.token_hash == _hash(token)).one_or_none()
    if row is None:
        return None
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        db.delete(row)
        db.commit()
        return None
    return row


def delete_session(db: Session, token: str) -> None:
    row = db.query(UserSession).filter(UserSession.token_hash == _hash(token)).one_or_none()
    if row is not None:
        db.delete(row)
        db.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest webapp/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add webapp/app/sessions.py webapp/tests/test_sessions.py
git commit -m "add db-backed session helpers"
```

---

### Task 4: Redirect-URI override in code exchange

The token exchange must send the redirect URI the authorization used; sign-in uses `signin_redirect_uri`, connect keeps `oauth_redirect_uri`.

**Files:**
- Modify: `webapp/app/oauth.py` (`exchange_code`)
- Modify: `webapp/tests/test_oauth.py`

- [ ] **Step 1: Write the failing test** — in `webapp/tests/test_oauth.py`, extend the import and append:

```python
from app.oauth import build_authorization_url, exchange_code, make_pkce, new_state
```

```python
def test_exchange_code_redirect_uri_default_and_override(monkeypatch, settings):
    posted = []

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {}

    def fake_post(url, data, timeout):
        posted.append(data)
        return FakeResp()

    monkeypatch.setattr("requests.post", fake_post)

    exchange_code(settings, code="c", code_verifier="v")
    assert posted[-1]["redirect_uri"] == settings.oauth_redirect_uri

    exchange_code(settings, code="c", code_verifier="v",
                  redirect_uri=settings.signin_redirect_uri)
    assert posted[-1]["redirect_uri"] == settings.signin_redirect_uri
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest webapp/tests/test_oauth.py -q`
Expected: FAIL — `TypeError: exchange_code() got an unexpected keyword argument 'redirect_uri'`.

- [ ] **Step 3: Implement** — in `webapp/app/oauth.py`, change the signature and the posted field:

```python
def exchange_code(
    settings: Settings, code: str, code_verifier: str, redirect_uri: str | None = None
) -> dict:
```

and in the `data=` dict:

```python
            "redirect_uri": redirect_uri or settings.oauth_redirect_uri,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest webapp/tests -q`
Expected: all pass (existing connect-callback tests are unaffected — their mocks are not called with the new kwarg).

- [ ] **Step 5: Commit**

```bash
git add webapp/app/oauth.py webapp/tests/test_oauth.py
git commit -m "allow overriding the redirect uri in code exchange"
```

---

### Task 5: Allowlist matcher and sign-in authorization URL

**Files:**
- Create: `webapp/app/routes/signin_routes.py` (helpers + empty router; routes come in Tasks 6-7)
- Create: `webapp/tests/test_signin.py`

- [ ] **Step 1: Write the failing tests** — create `webapp/tests/test_signin.py`:

```python
from urllib.parse import parse_qs, urlparse

from app.routes.signin_routes import build_signin_url, email_allowed


def test_email_allowed_empty_list_allows_anyone():
    assert email_allowed([], "anyone@example.com")


def test_email_allowed_matches_domain_exactly():
    allowed = ["goodlabs.kz"]
    assert email_allowed(allowed, "dilshat@goodlabs.kz")
    assert email_allowed(allowed, "DILSHAT@GOODLABS.KZ")
    assert not email_allowed(allowed, "x@sub.goodlabs.kz")
    assert not email_allowed(allowed, "x@evil-goodlabs.kz")


def test_email_allowed_matches_full_email():
    allowed = ["dilshatrakhimov@gmail.com"]
    assert email_allowed(allowed, "dilshatrakhimov@gmail.com")
    assert not email_allowed(allowed, "other@gmail.com")


def test_signin_url_uses_identity_scopes_only(settings):
    url = build_signin_url(settings, state="S", code_challenge="C")
    q = parse_qs(urlparse(url).query)
    assert q["redirect_uri"] == [settings.signin_redirect_uri]
    assert "openid" in q["scope"][0]
    assert "adwords" not in q["scope"][0]
    assert "access_type" not in q          # no offline refresh token for sign-in
    assert q["code_challenge_method"] == ["S256"]
    assert q["state"] == ["S"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest webapp/tests/test_signin.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.routes.signin_routes'`.

- [ ] **Step 3: Implement** — create `webapp/app/routes/signin_routes.py`:

```python
"""Google sign-in: OIDC start + callback, logout, and the /me probe."""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter

from app import oauth
from app.config import Settings

router = APIRouter()

STATE_TTL_SECONDS = 600
SIGNIN_SCOPES = ["openid", "email"]


def email_allowed(allowed: list[str], email: str) -> bool:
    """Entries with '@' match the full email; entries without match the
    email's domain exactly. Case-insensitive. Empty list allows anyone."""
    if not allowed:
        return True
    email = email.lower()
    domain = email.split("@", 1)[1] if "@" in email else ""
    for entry in allowed:
        entry = entry.lower()
        if "@" in entry:
            if entry == email:
                return True
        elif entry == domain:
            return True
    return False


def build_signin_url(settings: Settings, state: str, code_challenge: str) -> str:
    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": settings.signin_redirect_uri,
        "response_type": "code",
        "scope": " ".join(SIGNIN_SCOPES),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{oauth.AUTH_ENDPOINT}?{urlencode(params)}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest webapp/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add webapp/app/routes/signin_routes.py webapp/tests/test_signin.py
git commit -m "add sign-in allowlist matcher and authorization url"
```

---

### Task 6: API client fixture and the sign-in start route

**Files:**
- Modify: `webapp/tests/conftest.py` (add `make_api` / `api` fixtures)
- Modify: `webapp/tests/test_signin.py`
- Modify: `webapp/app/routes/signin_routes.py`
- Modify: `webapp/app/main.py`

- [ ] **Step 1: Add the API fixtures** — in `webapp/tests/conftest.py`, extend imports and append (mirrors `test_api._client`, plus per-test settings overrides):

```python
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.db import get_session
from app.main import create_app
from app.models import Base
```

```python
def _make_settings(**over):
    base = dict(
        database_url="sqlite://",
        fernet_keys=[Fernet.generate_key().decode()],
        google_oauth_client_id="cid",
        google_oauth_client_secret="secret",
        google_developer_token="DEV-TOKEN",
        oauth_redirect_uri="http://localhost:8000/oauth/google/callback",
        signin_redirect_uri="http://localhost:8000/auth/google/callback",
    )
    base.update(over)
    return Settings(**base)


@pytest.fixture
def make_api():
    def make(**settings_over):
        settings = _make_settings(**settings_over)
        engine = create_engine(
            "sqlite://", future=True,
            connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        Session = sessionmaker(engine, future=True)

        def override_session():
            with Session() as s:
                yield s

        app = create_app()
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_session] = override_session
        return TestClient(app), Session, settings

    return make


@pytest.fixture
def api(make_api):
    return make_api()
```

Update the existing `settings` fixture body to `return _make_settings()`.

- [ ] **Step 2: Write the failing test** — append to `webapp/tests/test_signin.py`:

```python
from app.models import OAuthState


def test_signin_start_redirects_with_signin_state(api):
    client, Session, settings = api
    r = client.get("/auth/google/start", follow_redirects=False)
    assert r.status_code == 302
    assert "accounts.google.com" in r.headers["location"]
    with Session() as s:
        row = s.query(OAuthState).one()
        assert row.purpose == "signin"
        assert row.user_id is None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest webapp/tests/test_signin.py -q`
Expected: FAIL — 404 (route does not exist).

- [ ] **Step 4: Implement** — in `webapp/app/routes/signin_routes.py`, extend imports:

```python
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import oauth
from app.config import Settings, get_settings
from app.db import get_session
from app.models import OAuthState
```

and append the route:

```python
@router.get("/auth/google/start")
def signin_start(
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_session),
):
    verifier, challenge = oauth.make_pkce()
    state = oauth.new_state()
    db.add(OAuthState(
        state=state,
        user_id=None,
        purpose="signin",
        code_verifier=verifier,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=STATE_TTL_SECONDS),
    ))
    db.commit()
    return RedirectResponse(build_signin_url(settings, state, challenge), status_code=302)
```

In `webapp/app/main.py`, import and include the router first:

```python
from app.routes import account_routes, auth_routes, signin_routes
```

```python
    app.include_router(signin_routes.router)
    app.include_router(auth_routes.router)
    app.include_router(account_routes.router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest webapp/tests -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add webapp/tests/conftest.py webapp/tests/test_signin.py webapp/app/routes/signin_routes.py webapp/app/main.py
git commit -m "add google sign-in start route"
```

---

### Task 7: Sign-in callback

**Files:**
- Modify: `webapp/app/routes/signin_routes.py`
- Modify: `webapp/tests/test_signin.py`

- [ ] **Step 1: Write the failing tests** — append to `webapp/tests/test_signin.py`:

```python
import app.oauth as oauth_mod
from app.models import User, UserSession


def _start_signin(client, Session):
    client.get("/auth/google/start", follow_redirects=False)
    with Session() as s:
        rows = s.query(OAuthState).filter(OAuthState.purpose == "signin").all()
        return rows[-1].state


def _mock_google(monkeypatch, sub="sub-1", email="dilshat@goodlabs.kz", verified=True):
    monkeypatch.setattr(
        oauth_mod, "exchange_code",
        lambda settings, code, code_verifier, redirect_uri=None: {"id_token": "idtok"})
    monkeypatch.setattr(
        oauth_mod, "verify_id_token",
        lambda settings, raw: {"sub": sub, "email": email, "email_verified": verified})


def test_signin_callback_sets_cookie_and_creates_user(api, monkeypatch):
    client, Session, settings = api
    state = _start_signin(client, Session)
    _mock_google(monkeypatch)

    r = client.get(f"/auth/google/callback?code=c&state={state}", follow_redirects=False)
    assert r.status_code == 200
    assert r.cookies.get("gads_session")
    assert "httponly" in r.headers["set-cookie"].lower()
    assert r.json()["user"]["email"] == "dilshat@goodlabs.kz"

    with Session() as s:
        user = s.query(User).one()
        assert user.google_sub == "sub-1"
        assert s.query(UserSession).one().user_id == user.id
        assert s.query(OAuthState).count() == 0   # consumed


def test_signin_twice_reuses_user_and_refreshes_email(api, monkeypatch):
    client, Session, settings = api

    state = _start_signin(client, Session)
    _mock_google(monkeypatch, sub="sub-1", email="old@goodlabs.kz")
    client.get(f"/auth/google/callback?code=c&state={state}", follow_redirects=False)

    state = _start_signin(client, Session)
    _mock_google(monkeypatch, sub="sub-1", email="new@goodlabs.kz")
    client.get(f"/auth/google/callback?code=c&state={state}", follow_redirects=False)

    with Session() as s:
        user = s.query(User).one()                # still one user
        assert user.email == "new@goodlabs.kz"
        assert s.query(UserSession).count() == 2  # one session per sign-in


def test_signin_callback_replay_rejected(api, monkeypatch):
    client, Session, settings = api
    state = _start_signin(client, Session)
    _mock_google(monkeypatch)
    client.get(f"/auth/google/callback?code=c&state={state}", follow_redirects=False)
    r2 = client.get(f"/auth/google/callback?code=c&state={state}", follow_redirects=False)
    assert r2.status_code == 400


def test_signin_callback_error_param_consumes_state(api):
    client, Session, settings = api
    state = _start_signin(client, Session)
    r = client.get(f"/auth/google/callback?error=access_denied&state={state}",
                   follow_redirects=False)
    assert r.status_code == 400
    assert "access_denied" in r.json()["detail"]
    with Session() as s:
        assert s.query(OAuthState).count() == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest webapp/tests/test_signin.py -q`
Expected: the four new tests FAIL with 404 (callback route does not exist).

- [ ] **Step 3: Implement** — in `webapp/app/routes/signin_routes.py`, extend imports:

```python
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, RedirectResponse

from app import oauth, sessions
from app.models import OAuthState, User
```

and append:

```python
SESSION_COOKIE = "gads_session"


@router.get("/auth/google/callback")
def signin_callback(
    state: str = Query(...),
    code: str | None = Query(None),
    error: str | None = Query(None),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_session),
):
    row = db.get(OAuthState, state)
    if row is None or row.purpose != "signin":
        raise HTTPException(status_code=400, detail="invalid or expired state")
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        db.delete(row)
        db.commit()
        raise HTTPException(status_code=400, detail="invalid or expired state")
    verifier = row.code_verifier
    db.delete(row)          # single-use
    db.commit()

    if error:
        raise HTTPException(status_code=400, detail=f"authorization failed: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="missing code")

    try:
        token = oauth.exchange_code(settings, code=code, code_verifier=verifier,
                                    redirect_uri=settings.signin_redirect_uri)
    except Exception:
        raise HTTPException(status_code=502, detail="token exchange failed")
    raw_id_token = token.get("id_token")
    if not raw_id_token:
        raise HTTPException(status_code=502, detail="no id token returned")
    try:
        claims = oauth.verify_id_token(settings, raw_id_token)
    except ValueError:
        raise HTTPException(status_code=502, detail="id token verification failed")

    email = claims.get("email")
    sub = claims.get("sub")

    user = db.query(User).filter(User.google_sub == sub).one_or_none()
    if user is None:
        user = User(google_sub=sub, email=email)
        db.add(user)
        db.commit()
    elif user.email != email:
        user.email = email
        db.commit()

    token_value, session_row = sessions.create_session(
        db, user.id, settings.session_max_hours)
    resp = JSONResponse({
        "user": {"id": user.id, "email": user.email},
        "expires_at": session_row.expires_at.isoformat(),
    })
    resp.set_cookie(
        SESSION_COOKIE, token_value,
        max_age=settings.session_max_hours * 3600,
        httponly=True, secure=settings.cookie_secure, samesite="lax", path="/",
    )
    return resp
```

Note: `cookie_secure` defaults to `True` and the test client uses http. Reading the cookie off the response (`r.cookies`, `set-cookie` header) works regardless; just never rely on the client *re-sending* a flow-issued `Secure` cookie over http in tests — later tasks mint sessions and set the cookie on the client directly.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest webapp/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add webapp/app/routes/signin_routes.py webapp/tests/test_signin.py
git commit -m "add sign-in callback with session cookie"
```

---

### Task 8: Allowlist and verified-email enforcement

**Files:**
- Modify: `webapp/app/routes/signin_routes.py`
- Modify: `webapp/tests/test_signin.py`

- [ ] **Step 1: Write the failing tests** — append to `webapp/tests/test_signin.py`:

```python
def test_signin_rejects_email_outside_allowlist(make_api, monkeypatch):
    client, Session, settings = make_api(allowed_signins=["goodlabs.kz"])
    state = _start_signin(client, Session)
    _mock_google(monkeypatch, email="outsider@example.com")
    r = client.get(f"/auth/google/callback?code=c&state={state}", follow_redirects=False)
    assert r.status_code == 403
    with Session() as s:
        assert s.query(User).count() == 0
        assert s.query(UserSession).count() == 0


def test_signin_rejects_unverified_email(api, monkeypatch):
    client, Session, settings = api
    state = _start_signin(client, Session)
    _mock_google(monkeypatch, verified=False)
    r = client.get(f"/auth/google/callback?code=c&state={state}", follow_redirects=False)
    assert r.status_code == 403
    with Session() as s:
        assert s.query(User).count() == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest webapp/tests/test_signin.py -q`
Expected: the two new tests FAIL — 200 instead of 403.

- [ ] **Step 3: Implement** — in `signin_callback`, between the claims extraction and the user upsert, insert:

```python
    if not email or not claims.get("email_verified", False):
        raise HTTPException(status_code=403, detail="email not verified")
    if not email_allowed(settings.allowed_signins, email):
        raise HTTPException(status_code=403, detail="email not allowed")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest webapp/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add webapp/app/routes/signin_routes.py webapp/tests/test_signin.py
git commit -m "enforce allowlist and verified email on sign-in"
```

---

### Task 9: Replace the identity stub

The big migration: cookie-based `get_current_user`, delete `X-Dev-User` and `dev_user_id`, rewrite every test that relied on them.

**Files:**
- Rewrite: `webapp/app/identity.py`
- Modify: `webapp/app/config.py` (remove `dev_user_id`)
- Delete: `webapp/tests/test_identity.py` (tests the stub; replaced by API tests)
- Modify: `webapp/tests/test_config.py` (drop the `dev_user_id` assert)
- Modify: `webapp/tests/test_api.py` (session-based identity)

- [ ] **Step 1: Write the failing test** — append to `webapp/tests/test_api.py`:

```python
def test_accounts_requires_signin():
    client, Session, settings = _client()
    r = client.get("/accounts")
    assert r.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest webapp/tests/test_api.py::test_accounts_requires_signin -q`
Expected: FAIL — 200 (the stub auto-creates a user).

- [ ] **Step 3: Rewrite identity** — replace the whole of `webapp/app/identity.py` with:

```python
"""Current-user resolution from the session cookie."""

from __future__ import annotations

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy.orm import Session

from app import sessions
from app.db import get_session
from app.models import User

SESSION_COOKIE = "gads_session"


def get_current_user(
    gads_session: str | None = Cookie(default=None),
    db: Session = Depends(get_session),
) -> User:
    if not gads_session:
        raise HTTPException(status_code=401, detail="not signed in")
    row = sessions.resolve_session(db, gads_session)
    if row is None:
        raise HTTPException(status_code=401, detail="not signed in")
    user = db.get(User, row.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="not signed in")
    return user
```

In `webapp/app/routes/signin_routes.py`, delete the local `SESSION_COOKIE = "gads_session"` line and import it instead:

```python
from app.identity import SESSION_COOKIE
```

In `webapp/app/config.py`, delete the `dev_user_id: str = "dev"` line.
In `webapp/tests/test_config.py`, delete the `assert s.dev_user_id == "dev"  # default` line.
Delete the stub test file:

```bash
git rm webapp/tests/test_identity.py
```

- [ ] **Step 4: Migrate `webapp/tests/test_api.py`** — add a sign-in helper after `_client()`:

```python
def _signin(client, Session, settings, user_id="ua"):
    """Mint a user + session directly and set the cookie on the client."""
    from app import sessions as sessions_mod
    with Session() as s:
        if s.get(User, user_id) is None:
            s.add(User(id=user_id))
            s.commit()
        token, _ = sessions_mod.create_session(s, user_id, settings.session_max_hours)
    client.cookies.set("gads_session", token)
    return token
```

Then update each test:

- `test_oauth_start_redirects_and_persists_state`: change the first two lines to

```python
    client, Session, settings = _client()
    _signin(client, Session, settings)
    r = client.get("/oauth/google/start", follow_redirects=False)
```

  and since sign-in tests also create states, assert on the connect state specifically:

```python
    with Session() as s:
        row = s.query(OAuthState).one()
        assert row.user_id == "ua"
```

- `test_oauth_callback_persists_token_and_consumes_state`,
  `test_oauth_callback_denied_returns_400_and_consumes_state`,
  `test_oauth_callback_persists_token_when_listing_fails`,
  `test_oauth_callback_rejects_missing_or_invalid_id_token`:
  insert `_signin(client, Session, settings)` immediately after the `_client()` line (before `/oauth/google/start`). In `test_oauth_callback_denied_returns_400_and_consumes_state`, the `_client()` call currently discards settings (`client, Session, _ = _client()`); change it to `client, Session, settings = _client()`.

- `test_select_rejects_customer_when_accessible_list_unknown`: replace the seeding block's user creation with `_signin` and drop the header:

```python
    client, Session, settings = _client()
    _signin(client, Session, settings, user_id="ua")
    with Session() as s:
        conn = Connection(user_id="ua", accessible_customers=None)
        s.add(conn)
        s.commit()
        conn_id = conn.id

    r = client.post(f"/accounts/{conn_id}/select", json={"customer_id": "9999999999"})
```

- `test_disconnect_revokes_and_clears_token` and
  `test_disconnect_clears_locally_when_revocation_fails`: add
  `_signin(client, Session, settings, user_id="ua")` after `_seed_connection`, and remove `headers={"X-Dev-User": "ua"}` from the POST.

- `test_disconnect_blocks_cross_tenant`: sign in as the other user:

```python
    conn_id = _seed_connection(Session, settings, user_id="ua")
    _signin(client, Session, settings, user_id="ub")
    r = client.post(f"/accounts/{conn_id}/disconnect")
```

- `test_summary_resolves_per_user_and_blocks_cross_tenant`: replace the two header-based GETs with cookie switches:

```python
    ta = _signin(client, Session, settings, user_id="ua")
    r = client.get(f"/accounts/{ca_id}/summary")
    assert r.status_code == 200
    assert r.json()["customer_id"] == "1111111111"

    _signin(client, Session, settings, user_id="ub")
    r2 = client.get(f"/accounts/{ca_id}/summary")   # ua's connection, ub's session
    assert r2.status_code == 404
```

  (note: `cb_id` is no longer needed in the second request — the point is ub probing ua's connection; keep the seeding as is. The `ta` variable is unused; name it `_` instead.)

- [ ] **Step 5: Run the suite and fix leftovers**

Run: `python -m pytest webapp/tests -q`
Expected: all pass. If a test still returns 401, it is missing a `_signin` call; if 404 vs 401 confuses, remember: 401 = no session, 404 = wrong owner.

- [ ] **Step 6: Lint**

Run: `python -m ruff check webapp`
Expected: clean (watch for now-unused imports in `identity.py` and `test_api.py` — remove `Header`, `resolve_user` leftovers).

- [ ] **Step 7: Commit**

```bash
git add -A webapp
git commit -m "replace identity stub with cookie sessions"
```

---

### Task 10: Logout and /me

**Files:**
- Modify: `webapp/app/routes/signin_routes.py`
- Modify: `webapp/tests/test_signin.py`

- [ ] **Step 1: Write the failing tests** — append to `webapp/tests/test_signin.py`:

```python
def _mint_session(client, Session, settings, user_id="u1"):
    from app import sessions as sessions_mod
    with Session() as s:
        if s.get(User, user_id) is None:
            s.add(User(id=user_id, email="u1@example.com"))
            s.commit()
        token, _ = sessions_mod.create_session(s, user_id, settings.session_max_hours)
    client.cookies.set("gads_session", token)
    return token


def test_me_requires_signin(api):
    client, _, _ = api
    assert client.get("/me").status_code == 401


def test_me_returns_signed_in_user(api):
    client, Session, settings = api
    _mint_session(client, Session, settings)
    r = client.get("/me")
    assert r.status_code == 200
    assert r.json() == {"id": "u1", "email": "u1@example.com"}


def test_logout_revokes_session(api):
    client, Session, settings = api
    _mint_session(client, Session, settings)
    r = client.post("/auth/logout")
    assert r.status_code == 200
    with Session() as s:
        assert s.query(UserSession).count() == 0
    client.cookies.clear()
    assert client.get("/me").status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest webapp/tests/test_signin.py -q`
Expected: the three new tests FAIL with 404 (routes do not exist).

- [ ] **Step 3: Implement** — in `webapp/app/routes/signin_routes.py`, extend imports:

```python
from fastapi import APIRouter, Cookie, Depends, HTTPException, Query

from app.identity import SESSION_COOKIE, get_current_user
```

and append:

```python
@router.post("/auth/logout")
def logout(
    gads_session: str | None = Cookie(default=None),
    db: Session = Depends(get_session),
):
    if gads_session:
        sessions.delete_session(db, gads_session)
    resp = JSONResponse({"status": "signed out"})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {"id": user.id, "email": user.email}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest webapp/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add webapp/app/routes/signin_routes.py webapp/tests/test_signin.py
git commit -m "add logout and me endpoints"
```

---

### Task 11: State-purpose enforcement on the connect callback

**Files:**
- Modify: `webapp/app/routes/auth_routes.py`
- Modify: `webapp/tests/test_api.py`

- [ ] **Step 1: Write the failing test** — append to `webapp/tests/test_api.py` (add `from datetime import datetime, timedelta, timezone` and `from app.models import OAuthState` to the imports if not present):

```python
def test_connect_callback_rejects_signin_state(monkeypatch):
    client, Session, settings = _client()
    _signin(client, Session, settings, user_id="ua")
    with Session() as s:
        s.add(OAuthState(
            state="S1", user_id="ua", purpose="signin", code_verifier="v",
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=600),
        ))
        s.commit()

    def no_exchange(*args, **kwargs):
        raise AssertionError("exchange must not run for a signin-purpose state")

    monkeypatch.setattr(oauth_mod, "exchange_code", no_exchange)

    r = client.get("/oauth/google/callback?code=c&state=S1", follow_redirects=False)
    assert r.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest webapp/tests/test_api.py::test_connect_callback_rejects_signin_state -q`
Expected: FAIL — the callback proceeds past state validation into the exchange stub, returning 502 instead of 400.

- [ ] **Step 3: Implement** — in `webapp/app/routes/auth_routes.py`:

In `oauth_callback`, extend the ownership check:

```python
    if row is None or row.user_id != user.id or row.purpose != "connect":
        raise HTTPException(status_code=400, detail="invalid or expired state")
```

In `oauth_start`, set the purpose explicitly when creating the state:

```python
    session.add(OAuthState(
        state=state,
        user_id=user.id,
        purpose="connect",
        code_verifier=verifier,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=STATE_TTL_SECONDS),
    ))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest webapp/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add webapp/app/routes/auth_routes.py webapp/tests/test_api.py
git commit -m "enforce state purpose on the connect callback"
```

---

### Task 12: Same-origin enforcement for unsafe methods

**Files:**
- Create: `webapp/app/csrf.py`
- Modify: `webapp/app/main.py`
- Modify: `webapp/tests/test_signin.py`

- [ ] **Step 1: Write the failing tests** — append to `webapp/tests/test_signin.py`:

```python
def test_cross_origin_post_rejected(api):
    client, _, _ = api
    r = client.post("/auth/logout", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_same_origin_post_allowed(api):
    client, _, _ = api
    r = client.post("/auth/logout", headers={"Origin": "http://localhost:8000"})
    assert r.status_code == 200


def test_get_ignores_origin(api):
    client, _, _ = api
    r = client.get("/me", headers={"Origin": "https://evil.example"})
    assert r.status_code == 401   # auth failure, not a csrf rejection
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest webapp/tests/test_signin.py -q`
Expected: `test_cross_origin_post_rejected` FAILS — 200 instead of 403; the other two pass already (they pin current behavior).

- [ ] **Step 3: Implement** — create `webapp/app/csrf.py`:

```python
"""Same-origin enforcement for unsafe methods, on top of SameSite=Lax."""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import Depends, HTTPException, Request

from app.config import Settings, get_settings

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def app_origin(settings: Settings) -> str:
    u = urlparse(settings.signin_redirect_uri)
    return f"{u.scheme}://{u.netloc}"


def require_same_origin(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    if request.method in SAFE_METHODS:
        return
    origin = request.headers.get("origin")
    if origin is not None and origin != app_origin(settings):
        raise HTTPException(status_code=403, detail="cross-origin request rejected")
```

In `webapp/app/main.py`, wire it as a global dependency:

```python
from fastapi import Depends, FastAPI

from app.csrf import require_same_origin
from app.routes import account_routes, auth_routes, signin_routes


def create_app() -> FastAPI:
    app = FastAPI(title="Google Ads Agents - web backend",
                  dependencies=[Depends(require_same_origin)])
    app.include_router(signin_routes.router)
    app.include_router(auth_routes.router)
    app.include_router(account_routes.router)
    return app
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest webapp/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add webapp/app/csrf.py webapp/app/main.py webapp/tests/test_signin.py
git commit -m "reject cross-origin unsafe requests"
```

---

### Task 13: Final verification

- [ ] **Step 1: Full suite**

Run: `python -m pytest scripts webapp/tests -q`
Expected: all pass (200+ tests).

- [ ] **Step 2: Lint**

Run: `python -m ruff check scripts webapp hooks`
Expected: `All checks passed!`

- [ ] **Step 3: Confirm no stub remnants**

Run: `python -m pytest webapp/tests -q; git grep -n "X-Dev-User" -- webapp; git grep -n "dev_user_id" -- webapp`
Expected: both greps return nothing.

- [ ] **Step 4: Commit anything outstanding**

```bash
git status --short
```

Expected: clean tree (every task committed as it went).

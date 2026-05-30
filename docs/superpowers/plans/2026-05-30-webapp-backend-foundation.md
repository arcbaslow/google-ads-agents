# Web App Backend Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a multi-tenant FastAPI backend that resolves Google Ads credentials per-user from an encrypted Postgres store, with a web OAuth redirect flow, while leaving the CLI toolkit unchanged.

**Architecture:** A new `scripts/gads_provider.py` introduces a `CredentialProvider` seam (protocol + `contextvar` + registry) that `gads_client.build_client()` routes through; the CLI keeps a default `FileCredentialProvider`. A new `webapp/` package adds a `WebCredentialProvider` bound per request, a `DbTokenStore` (Fernet-encrypted refresh tokens), and PKCE-hardened OAuth start/callback routes. The web app imports the toolkit; the toolkit never imports the web app.

**Tech Stack:** Python 3.10+, FastAPI, SQLAlchemy 2.0 + Alembic, Postgres (prod) / SQLite (tests), `cryptography` (Fernet), `pydantic-settings`, `google-auth-oauthlib` (already a dep). Tests: pytest + FastAPI `TestClient`.

**Repo conventions (from CLAUDE.md):** Commit messages are short imperative, sentence case OK, NO Conventional-Commits prefixes (`feat:`/`fix:`), NO `Co-Authored-By`, NO generated-with footer. Comments only where the *why* is non-obvious. Never commit secrets.

**Design spec:** `docs/superpowers/specs/2026-05-30-webapp-backend-foundation-design.md`. Read it once for context if you need the rationale; the tasks below are self-contained.

---

## File structure

Created/modified across the plan:

- `scripts/gads_provider.py` (create) — `CredentialProvider` protocol, the `contextvar`, `get_active_provider()`, `bind_provider()`, `FileCredentialProvider`.
- `scripts/gads_client.py` (modify) — `build_client()` routes through `get_active_provider()`.
- `scripts/test_gads_provider.py` (create) — seam tests.
- `webapp/requirements.txt` (create) — web deps.
- `webapp/app/__init__.py`, `webapp/app/config.py` (create) — typed settings.
- `webapp/app/crypto.py` (create) — Fernet versioned encrypt/decrypt.
- `webapp/app/db.py`, `webapp/app/models.py` (create) — engine/session + ORM.
- `webapp/app/tokenstore_db.py` (create) — `DbTokenStore`.
- `webapp/app/providers.py` (create) — `WebCredentialProvider`, `ConnectionAuthError`.
- `webapp/app/identity.py` (create) — current-user stub.
- `webapp/app/oauth.py` (create) — PKCE + auth-URL + token-exchange helpers.
- `webapp/app/routes/auth_routes.py`, `webapp/app/routes/account_routes.py` (create) — endpoints.
- `webapp/app/main.py` (create) — app factory + wiring.
- `webapp/alembic/*` + `webapp/alembic.ini` (create) — migrations.
- `webapp/tests/conftest.py` + `webapp/tests/test_*.py` (create) — tests.

Column-type portability (resolves the spec's open question): models use SQLAlchemy types that render correctly on both engines — `String(36)` for ids, `LargeBinary` for the encrypted token (bytea on PG, BLOB on SQLite), and `JSONB().with_variant(JSON(), "sqlite")` for the customer list. Tests build the schema with `Base.metadata.create_all()` on SQLite; prod uses Alembic against Postgres.

---

### Task 1: Credential provider seam in the toolkit

**Files:**
- Create: `scripts/gads_provider.py`
- Modify: `scripts/gads_client.py`
- Test: `scripts/test_gads_provider.py`

This is pure toolkit work — no web deps. It must not change CLI behavior: the existing suite stays green.

- [ ] **Step 1: Write the failing tests**

Create `scripts/test_gads_provider.py`:

```python
from __future__ import annotations

import sys
import types

import gads_provider


def test_default_is_file_provider():
    assert isinstance(gads_provider.get_active_provider(), gads_provider.FileCredentialProvider)


def test_bind_swaps_provider_and_resets():
    class Fake:
        def get_credentials(self): return "C"
        def get_developer_token(self): return "DEV"
        def get_login_customer_id(self): return "111"

    fake = Fake()
    with gads_provider.bind_provider(fake):
        assert gads_provider.get_active_provider() is fake
    assert isinstance(gads_provider.get_active_provider(), gads_provider.FileCredentialProvider)


def test_build_client_uses_active_provider(monkeypatch):
    # Inject a fake google-ads client module so build_client() imports it.
    captured = {}

    class FakeClient:
        @classmethod
        def load_from_dict(cls, cfg):
            captured.update(cfg)
            return "CLIENT"

    fake_mod = types.ModuleType("google.ads.googleads.client")
    fake_mod.GoogleAdsClient = FakeClient
    monkeypatch.setitem(sys.modules, "google.ads.googleads.client", fake_mod)

    class Fake:
        def get_credentials(self): return "CREDS"
        def get_developer_token(self): return "DEV"
        def get_login_customer_id(self): return "1234567890"

    import gads_client
    with gads_provider.bind_provider(Fake()):
        assert gads_client.build_client() == "CLIENT"

    assert captured["developer_token"] == "DEV"
    assert captured["credentials"] == "CREDS"
    assert captured["login_customer_id"] == "1234567890"
    assert captured["use_proto_plus"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd scripts && python -m pytest test_gads_provider.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'gads_provider'`.

- [ ] **Step 3: Create the provider module**

Create `scripts/gads_provider.py`:

```python
"""Credential-resolution seam.

build_client() resolves credentials through the *active* CredentialProvider.
The CLI default (FileCredentialProvider) wraps gads_auth unchanged. The web app
binds a per-request provider via bind_provider(); the contextvar isolates it
across concurrent requests. This module owns the contextvar and registry so the
toolkit never has to import the web app.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Any, Protocol


class CredentialProvider(Protocol):
    def get_credentials(self) -> Any: ...
    def get_developer_token(self) -> str: ...
    def get_login_customer_id(self) -> str | None: ...


class FileCredentialProvider:
    """Default: resolve from the active local profile via gads_auth."""

    def get_credentials(self) -> Any:
        import gads_auth
        return gads_auth.get_credentials()

    def get_developer_token(self) -> str:
        import gads_auth
        return gads_auth.get_developer_token()

    def get_login_customer_id(self) -> str | None:
        import gads_auth
        return gads_auth.get_login_customer_id()


_default = FileCredentialProvider()
_active: contextvars.ContextVar = contextvars.ContextVar("gads_active_provider", default=None)


def get_active_provider() -> CredentialProvider:
    return _active.get() or _default


@contextmanager
def bind_provider(provider: CredentialProvider):
    token = _active.set(provider)
    try:
        yield
    finally:
        _active.reset(token)
```

- [ ] **Step 4: Route build_client through the provider**

In `scripts/gads_client.py`, replace the body of `build_client()`. The current code reads:

```python
def build_client():
    """Return a configured GoogleAdsClient for the active profile."""
    from google.ads.googleads.client import GoogleAdsClient

    cfg: dict[str, Any] = {
        "developer_token": gads_auth.get_developer_token(),
        "use_proto_plus": True,
        "credentials": gads_auth.get_credentials(),
    }
    login = gads_auth.get_login_customer_id()
    if login:
        cfg["login_customer_id"] = login
    return GoogleAdsClient.load_from_dict(cfg)
```

Replace it with:

```python
def build_client():
    """Return a configured GoogleAdsClient for the active credential provider."""
    from google.ads.googleads.client import GoogleAdsClient
    import gads_provider

    provider = gads_provider.get_active_provider()
    cfg: dict[str, Any] = {
        "developer_token": provider.get_developer_token(),
        "use_proto_plus": True,
        "credentials": provider.get_credentials(),
    }
    login = provider.get_login_customer_id()
    if login:
        cfg["login_customer_id"] = login
    return GoogleAdsClient.load_from_dict(cfg)
```

Leave the module-level `import gads_auth` in place (other functions may use it); if ruff flags it as unused after this edit, remove the top-level `import gads_auth` line.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd scripts && python -m pytest test_gads_provider.py -q`
Expected: PASS (3 passed).

- [ ] **Step 6: Run the full CLI suite (regression)**

Run: `cd scripts && python -m pytest -q`
Expected: PASS — previously 154 passed, now 157 (the 3 new tests). No existing test changes behavior.

- [ ] **Step 7: Lint**

Run: `cd "C:/Program Data/Repository/google-ads-agents" && python -m ruff check scripts/gads_provider.py scripts/gads_client.py scripts/test_gads_provider.py`
Expected: `All checks passed!`

- [ ] **Step 8: Commit**

```bash
git add scripts/gads_provider.py scripts/gads_client.py scripts/test_gads_provider.py
git commit -m "route build_client through a credential provider seam"
```

---

### Task 2: webapp package skeleton and typed config

**Files:**
- Create: `webapp/requirements.txt`
- Create: `webapp/app/__init__.py` (empty)
- Create: `webapp/app/config.py`
- Create: `webapp/tests/__init__.py` (empty)
- Test: `webapp/tests/test_config.py`

Run all webapp commands from the repo root. Tests import as `from app.config import ...`, so pytest must run with `webapp/` on the path — Step 5 uses `cd webapp && python -m pytest`.

- [ ] **Step 1: Create the requirements file**

Create `webapp/requirements.txt`:

```
fastapi>=0.110
uvicorn[standard]>=0.29
sqlalchemy>=2.0
alembic>=1.13
psycopg2-binary>=2.9
cryptography>=42.0
pydantic-settings>=2.2
httpx>=0.27
requests>=2.31
google-auth-oauthlib>=1.2.0
```

(`httpx` is required by FastAPI's `TestClient`; `requests` is used by `oauth.exchange_code`.)

- [ ] **Step 2: Install web deps**

Run: `pip install -r webapp/requirements.txt`
Expected: installs without error.

- [ ] **Step 3: Write the failing test**

Create empty `webapp/app/__init__.py` and `webapp/tests/__init__.py`. Then create `webapp/tests/test_config.py`:

```python
import pytest
from cryptography.fernet import Fernet

from app.config import Settings


def _env(**over):
    base = dict(
        DATABASE_URL="sqlite://",
        FERNET_KEYS=f'["{Fernet.generate_key().decode()}"]',
        GOOGLE_OAUTH_CLIENT_ID="cid",
        GOOGLE_OAUTH_CLIENT_SECRET="secret",
        GOOGLE_DEVELOPER_TOKEN="dev",
        OAUTH_REDIRECT_URI="http://localhost:8000/oauth/google/callback",
    )
    base.update(over)
    return base


def test_settings_load_from_env(monkeypatch):
    for k, v in _env().items():
        monkeypatch.setenv(k, v)
    s = Settings()
    assert s.google_developer_token == "dev"
    assert s.dev_user_id == "dev"  # default
    assert len(s.fernet_keys) == 1


def test_missing_required_raises(monkeypatch):
    for k in ("DATABASE_URL", "FERNET_KEYS", "GOOGLE_OAUTH_CLIENT_ID",
              "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_DEVELOPER_TOKEN",
              "OAUTH_REDIRECT_URI"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(Exception):
        Settings()
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `cd webapp && python -m pytest tests/test_config.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.config'`.

- [ ] **Step 5: Implement config**

Create `webapp/app/config.py`:

```python
"""Typed settings from env. Fail fast on missing required values at startup."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    fernet_keys: list[str]                 # oldest first, newest last (append-only)
    google_oauth_client_id: str
    google_oauth_client_secret: str
    google_developer_token: str
    oauth_redirect_uri: str
    dev_user_id: str = "dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd webapp && python -m pytest tests/test_config.py -q`
Expected: PASS (2 passed).

- [ ] **Step 7: Commit**

```bash
git add webapp/requirements.txt webapp/app/__init__.py webapp/app/config.py webapp/tests/__init__.py webapp/tests/test_config.py
git commit -m "add webapp package skeleton and typed settings"
```

---

### Task 3: Fernet encryption with key versioning

**Files:**
- Create: `webapp/app/crypto.py`
- Test: `webapp/tests/test_crypto.py`

Versioning is append-only: `fernet_keys` is ordered oldest→newest, the newest (last) key encrypts, and the stored integer `version` is the key's index, which stays stable as new keys are appended.

- [ ] **Step 1: Write the failing tests**

Create `webapp/tests/test_crypto.py`:

```python
from cryptography.fernet import Fernet

from app.crypto import Crypto


def test_round_trip():
    c = Crypto([Fernet.generate_key().decode()])
    ct, ver = c.encrypt("refresh-token-value")
    assert ver == 0
    assert ct != b"refresh-token-value"
    assert c.decrypt(ct, ver) == "refresh-token-value"


def test_rotation_keeps_old_versions_decryptable():
    k0 = Fernet.generate_key().decode()
    c_old = Crypto([k0])
    ct0, ver0 = c_old.encrypt("old-secret")
    assert ver0 == 0

    k1 = Fernet.generate_key().decode()
    c_new = Crypto([k0, k1])           # appended; current is now index 1
    ct1, ver1 = c_new.encrypt("new-secret")
    assert ver1 == 1
    assert c_new.decrypt(ct0, ver0) == "old-secret"   # old version still decrypts
    assert c_new.decrypt(ct1, ver1) == "new-secret"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd webapp && python -m pytest tests/test_crypto.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.crypto'`.

- [ ] **Step 3: Implement crypto**

Create `webapp/app/crypto.py`:

```python
"""Fernet encryption with append-only key versioning.

`keys` is ordered oldest -> newest. The newest key encrypts; the stored integer
version is the key's index, stable across future appends. Rotation = append a
new key; existing ciphertext still decrypts under its stored version.
"""

from __future__ import annotations

from cryptography.fernet import Fernet


class Crypto:
    def __init__(self, keys: list[str]):
        if not keys:
            raise ValueError("Crypto requires at least one key")
        self._fernets = [Fernet(k.encode()) for k in keys]

    def encrypt(self, plaintext: str) -> tuple[bytes, int]:
        version = len(self._fernets) - 1
        return self._fernets[version].encrypt(plaintext.encode()), version

    def decrypt(self, token: bytes, version: int) -> str:
        return self._fernets[version].decrypt(token).decode()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd webapp && python -m pytest tests/test_crypto.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add webapp/app/crypto.py webapp/tests/test_crypto.py
git commit -m "add fernet encryption with key versioning"
```

---

### Task 4: ORM models and session

**Files:**
- Create: `webapp/app/db.py`
- Create: `webapp/app/models.py`
- Create: `webapp/tests/conftest.py`
- Test: `webapp/tests/test_models.py`

- [ ] **Step 1: Write the failing test and shared fixtures**

Create `webapp/tests/conftest.py`:

```python
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.models import Base


@pytest.fixture
def settings():
    return Settings(
        database_url="sqlite://",
        fernet_keys=[Fernet.generate_key().decode()],
        google_oauth_client_id="cid",
        google_oauth_client_secret="secret",
        google_developer_token="DEV-TOKEN",
        oauth_redirect_uri="http://localhost:8000/oauth/google/callback",
    )


@pytest.fixture
def session(settings):
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine, future=True)
    with Session() as s:
        yield s
```

Create `webapp/tests/test_models.py`:

```python
from app.models import User, Connection


def test_user_and_connection_roundtrip(session):
    u = User(email="m@example.com")
    session.add(u)
    session.flush()
    assert u.id  # uuid populated

    c = Connection(
        user_id=u.id,
        google_email="m@gmail.com",
        refresh_token=b"\x01\x02",
        token_version=0,
        customer_id="1234567890",
        accessible_customers=["1234567890", "2222222222"],
        scopes="adwords",
    )
    session.add(c)
    session.flush()
    got = session.get(Connection, c.id)
    assert got.user_id == u.id
    assert got.accessible_customers == ["1234567890", "2222222222"]
    assert got.refresh_token == b"\x01\x02"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd webapp && python -m pytest tests/test_models.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models'`.

- [ ] **Step 3: Implement models**

Create `webapp/app/models.py`:

```python
"""ORM models. Portable column types so tests run on SQLite, prod on Postgres."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON, DateTime, ForeignKey, Integer, LargeBinary, String, Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


_JSON_LIST = JSONB().with_variant(JSON(), "sqlite")


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str | None] = mapped_column(String(320), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Connection(Base):
    __tablename__ = "connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    google_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    refresh_token: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    token_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    customer_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    login_customer_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    accessible_customers: Mapped[list | None] = mapped_column(_JSON_LIST, nullable=True)
    scopes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OAuthState(Base):
    __tablename__ = "oauth_states"

    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    code_verifier: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 4: Implement the session module**

Create `webapp/app/db.py`:

```python
"""Engine/session wiring and the FastAPI session dependency."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import Base

_engine = None
_Session: sessionmaker | None = None


def _ensure() -> sessionmaker:
    global _engine, _Session
    if _Session is None:
        _engine = create_engine(get_settings().database_url, future=True)
        Base.metadata.create_all(_engine)  # dev/bootstrap; prod schema via Alembic
        _Session = sessionmaker(_engine, future=True)
    return _Session


def get_session() -> Iterator[Session]:
    factory = _ensure()
    with factory() as session:
        yield session
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd webapp && python -m pytest tests/test_models.py -q`
Expected: PASS (1 passed).

- [ ] **Step 6: Commit**

```bash
git add webapp/app/db.py webapp/app/models.py webapp/tests/conftest.py webapp/tests/test_models.py
git commit -m "add orm models and session wiring"
```

---

### Task 5: DbTokenStore

**Files:**
- Create: `webapp/app/tokenstore_db.py`
- Test: `webapp/tests/test_tokenstore_db.py`

`DbTokenStore` satisfies the same `get/set(key, record)` contract as the toolkit's `LocalFileTokenStore`, keyed by `connection_id`. `get()` decrypts the per-user refresh token and merges the app `client_id`/`client_secret` from settings, so `OAuthClientBackend` is untouched. `set()` encrypts the refresh token onto an existing connection row.

- [ ] **Step 1: Write the failing tests**

Create `webapp/tests/test_tokenstore_db.py`:

```python
import pytest

from app.crypto import Crypto
from app.models import Connection, User
from app.tokenstore_db import DbTokenStore


@pytest.fixture
def conn(session):
    u = User(email="m@example.com")
    session.add(u)
    session.flush()
    c = Connection(user_id=u.id, google_email="m@gmail.com")
    session.add(c)
    session.flush()
    return c


def _store(session, settings):
    return DbTokenStore(session, Crypto(settings.fernet_keys), settings)


def test_get_none_when_no_token(session, settings, conn):
    assert _store(session, settings).get(conn.id) is None


def test_set_then_get_round_trips_and_merges_config(session, settings, conn):
    store = _store(session, settings)
    store.set(conn.id, {"refresh_token": "rtok"})
    rec = store.get(conn.id)
    assert rec == {
        "refresh_token": "rtok",
        "client_id": settings.google_oauth_client_id,
        "client_secret": settings.google_oauth_client_secret,
    }
    # token is encrypted at rest, not stored in cleartext
    session.refresh(conn)
    assert conn.refresh_token != b"rtok"
    assert conn.token_version == 0


def test_get_unknown_key_returns_none(session, settings):
    assert _store(session, settings).get("nonexistent") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd webapp && python -m pytest tests/test_tokenstore_db.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.tokenstore_db'`.

- [ ] **Step 3: Implement DbTokenStore**

Create `webapp/app/tokenstore_db.py`:

```python
"""DbTokenStore: TokenStore backed by the connections table.

Only the per-user refresh token is stored (encrypted). client_id/client_secret
come from app config, so the record handed to OAuthClientBackend matches the
LocalFileTokenStore shape and the backend needs no change.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.crypto import Crypto
from app.models import Connection


class DbTokenStore:
    def __init__(self, session: Session, crypto: Crypto, settings: Settings):
        self._session = session
        self._crypto = crypto
        self._settings = settings

    def get(self, key: str) -> dict[str, Any] | None:
        conn = self._session.get(Connection, key)
        if not conn or conn.refresh_token is None or conn.token_version is None:
            return None
        return {
            "refresh_token": self._crypto.decrypt(conn.refresh_token, conn.token_version),
            "client_id": self._settings.google_oauth_client_id,
            "client_secret": self._settings.google_oauth_client_secret,
        }

    def set(self, key: str, record: dict[str, Any]) -> None:
        conn = self._session.get(Connection, key)
        if conn is None:
            raise KeyError(f"connection {key!r} does not exist")
        if "refresh_token" in record:
            ct, ver = self._crypto.encrypt(record["refresh_token"])
            conn.refresh_token = ct
            conn.token_version = ver
        self._session.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd webapp && python -m pytest tests/test_tokenstore_db.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add webapp/app/tokenstore_db.py webapp/tests/test_tokenstore_db.py
git commit -m "add DbTokenStore with encrypted refresh tokens"
```

---

### Task 6: WebCredentialProvider

**Files:**
- Create: `webapp/app/providers.py`
- Test: `webapp/tests/test_providers.py`

`WebCredentialProvider` implements the toolkit's `CredentialProvider`. It reuses the 0.6.0 `OAuthClientBackend` (in `scripts/gads_authflow.py`) to turn a stored record into refreshed credentials. The web app must import from `scripts/`, so tests add the scripts dir to `sys.path` (Step 1).

- [ ] **Step 1: Write the failing tests**

Create `webapp/tests/test_providers.py`:

```python
import os
import sys

import pytest

# Make the toolkit (scripts/) importable for OAuthClientBackend reuse.
SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from app.models import Connection, User
from app.providers import ConnectionAuthError, WebCredentialProvider
from app.tokenstore_db import DbTokenStore
from app.crypto import Crypto


@pytest.fixture
def conn(session):
    u = User(email="m@example.com")
    session.add(u)
    session.flush()
    c = Connection(user_id=u.id, google_email="m@gmail.com",
                   customer_id="1234567890", login_customer_id="9999999999")
    session.add(c)
    session.flush()
    return c


def _provider(session, settings, conn):
    store = DbTokenStore(session, Crypto(settings.fernet_keys), settings)
    return WebCredentialProvider(store, settings, conn)


def test_dev_token_and_login_id(session, settings, conn):
    p = _provider(session, settings, conn)
    assert p.get_developer_token() == "DEV-TOKEN"
    assert p.get_login_customer_id() == "9999999999"


def test_get_credentials_without_token_raises(session, settings, conn):
    p = _provider(session, settings, conn)
    with pytest.raises(ConnectionAuthError):
        p.get_credentials()


def test_get_credentials_builds_backend(session, settings, conn, monkeypatch):
    store = DbTokenStore(session, Crypto(settings.fernet_keys), settings)
    store.set(conn.id, {"refresh_token": "rtok"})

    captured = {}
    import gads_authflow

    class FakeBackend:
        def __init__(self, record):
            captured["record"] = record
        def credentials(self):
            return "REFRESHED"

    monkeypatch.setattr(gads_authflow, "OAuthClientBackend", FakeBackend)

    p = WebCredentialProvider(store, settings, conn)
    assert p.get_credentials() == "REFRESHED"
    assert captured["record"]["refresh_token"] == "rtok"
    assert captured["record"]["client_id"] == settings.google_oauth_client_id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd webapp && python -m pytest tests/test_providers.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.providers'`.

- [ ] **Step 3: Implement the provider**

Create `webapp/app/providers.py`:

```python
"""WebCredentialProvider: per-request credential resolution for a connection.

Reuses the 0.6.0 OAuthClientBackend to refresh credentials from the stored
record. No 24h session cap here - that is a CLI-local concern.
"""

from __future__ import annotations

from typing import Any

from app.config import Settings
from app.models import Connection
from app.tokenstore_db import DbTokenStore


class ConnectionAuthError(RuntimeError):
    """The connection has no usable refresh token; the user must reconnect."""


class WebCredentialProvider:
    def __init__(self, store: DbTokenStore, settings: Settings, connection: Connection):
        self._store = store
        self._settings = settings
        self._connection = connection

    def get_credentials(self) -> Any:
        import gads_authflow

        record = self._store.get(self._connection.id)
        if not record:
            raise ConnectionAuthError(
                f"connection {self._connection.id} has no stored refresh token"
            )
        return gads_authflow.OAuthClientBackend(record).credentials()

    def get_developer_token(self) -> str:
        return self._settings.google_developer_token

    def get_login_customer_id(self) -> str | None:
        return self._connection.login_customer_id
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd webapp && python -m pytest tests/test_providers.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add webapp/app/providers.py webapp/tests/test_providers.py
git commit -m "add WebCredentialProvider reusing the oauth client backend"
```

---

### Task 7: Current-user identity stub

**Files:**
- Create: `webapp/app/identity.py`
- Test: `webapp/tests/test_identity.py`

The stub resolves a user from the `X-Dev-User` header (a user id), falling back to a seeded default user keyed by `settings.dev_user_id`. Either way it returns a `User`, creating the default row on first use. Real sign-in replaces this module later.

- [ ] **Step 1: Write the failing tests**

Create `webapp/tests/test_identity.py`:

```python
from app.identity import resolve_user
from app.models import User


def test_seeds_default_user_when_no_header(session, settings):
    u = resolve_user(session, settings, dev_user_header=None)
    assert isinstance(u, User)
    assert u.id == settings.dev_user_id
    # idempotent
    u2 = resolve_user(session, settings, dev_user_header=None)
    assert u2.id == u.id


def test_resolves_existing_user_by_header(session, settings):
    existing = User(id="abc123", email="a@example.com")
    session.add(existing)
    session.commit()
    u = resolve_user(session, settings, dev_user_header="abc123")
    assert u.id == "abc123"


def test_unknown_header_user_is_created(session, settings):
    u = resolve_user(session, settings, dev_user_header="newid")
    assert u.id == "newid"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd webapp && python -m pytest tests/test_identity.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.identity'`.

- [ ] **Step 3: Implement identity**

Create `webapp/app/identity.py`:

```python
"""Current-user resolution. Stub for this slice; real sign-in replaces it.

resolve_user() is pure (takes a session) so it is unit-testable. get_current_user
is the FastAPI dependency wrapper.
"""

from __future__ import annotations

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.models import User


def resolve_user(session: Session, settings: Settings, dev_user_header: str | None) -> User:
    user_id = dev_user_header or settings.dev_user_id
    user = session.get(User, user_id)
    if user is None:
        user = User(id=user_id)
        session.add(user)
        session.commit()
    return user


def get_current_user(
    x_dev_user: str | None = Header(default=None),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> User:
    return resolve_user(session, settings, x_dev_user)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd webapp && python -m pytest tests/test_identity.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add webapp/app/identity.py webapp/tests/test_identity.py
git commit -m "add current-user identity stub"
```

---

### Task 8: OAuth helpers (PKCE, auth URL, token exchange)

**Files:**
- Create: `webapp/app/oauth.py`
- Test: `webapp/tests/test_oauth.py`

Pure helpers, no FastAPI, so they unit-test cleanly. The auth route (Task 9) wires them to HTTP and the DB.

- [ ] **Step 1: Write the failing tests**

Create `webapp/tests/test_oauth.py`:

```python
from urllib.parse import urlparse, parse_qs

from app.oauth import build_authorization_url, make_pkce, new_state


def test_make_pkce_pair():
    verifier, challenge = make_pkce()
    assert 43 <= len(verifier) <= 128
    assert challenge and challenge != verifier


def test_new_state_is_random_and_urlsafe():
    a, b = new_state(), new_state()
    assert a != b
    assert len(a) >= 32


def test_authorization_url_has_required_params(settings):
    url = build_authorization_url(
        settings, state="STATE123", code_challenge="CHAL"
    )
    q = parse_qs(urlparse(url).query)
    assert q["client_id"] == [settings.google_oauth_client_id]
    assert q["redirect_uri"] == [settings.oauth_redirect_uri]
    assert q["response_type"] == ["code"]
    assert q["access_type"] == ["offline"]
    assert q["prompt"] == ["consent"]
    assert q["state"] == ["STATE123"]
    assert q["code_challenge"] == ["CHAL"]
    assert q["code_challenge_method"] == ["S256"]
    assert "https://www.googleapis.com/auth/adwords" in q["scope"][0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd webapp && python -m pytest tests/test_oauth.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.oauth'`.

- [ ] **Step 3: Implement the helpers**

Create `webapp/app/oauth.py`:

```python
"""OAuth helpers: PKCE, the Google authorization URL, and code exchange.

The web flow uses the app-owned Web client (config), the restricted `adwords`
scope, offline access + forced consent (to obtain a refresh token), and PKCE.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import urlencode

from app.config import Settings

ADWORDS_SCOPE = "https://www.googleapis.com/auth/adwords"
OPENID_SCOPES = ["openid", "email"]
AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def make_pkce() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


def new_state() -> str:
    return secrets.token_urlsafe(32)


def build_authorization_url(settings: Settings, state: str, code_challenge: str) -> str:
    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": settings.oauth_redirect_uri,
        "response_type": "code",
        "scope": " ".join([ADWORDS_SCOPE, *OPENID_SCOPES]),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


def exchange_code(settings: Settings, code: str, code_verifier: str) -> dict:
    """Exchange an authorization code for tokens. Returns the token response dict
    with at least `refresh_token`. Network call; mocked in tests."""
    import requests

    resp = requests.post(
        TOKEN_ENDPOINT,
        data={
            "client_id": settings.google_oauth_client_id,
            "client_secret": settings.google_oauth_client_secret,
            "code": code,
            "code_verifier": code_verifier,
            "grant_type": "authorization_code",
            "redirect_uri": settings.oauth_redirect_uri,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd webapp && python -m pytest tests/test_oauth.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add webapp/app/oauth.py webapp/tests/test_oauth.py
git commit -m "add oauth pkce and authorization-url helpers"
```

---

### Task 9: App factory, auth routes, account routes

**Files:**
- Create: `webapp/app/main.py`
- Create: `webapp/app/routes/__init__.py` (empty)
- Create: `webapp/app/routes/auth_routes.py`
- Create: `webapp/app/routes/account_routes.py`
- Test: `webapp/tests/test_api.py`

This task wires everything into HTTP endpoints and proves the seam end-to-end, including the cross-tenant isolation guarantee. It is the largest task; the app factory exposes dependency seams (`get_session`, `get_settings`, `get_current_user`) that the test overrides.

- [ ] **Step 1: Write the failing integration tests**

Create `webapp/tests/test_api.py`:

```python
import os
import sys

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import app.oauth as oauth_mod
from app.config import Settings
from app.db import get_session
from app.config import get_settings
from app.models import Base, Connection, User
from app.main import create_app


def _settings():
    return Settings(
        database_url="sqlite://",
        fernet_keys=[Fernet.generate_key().decode()],
        google_oauth_client_id="cid",
        google_oauth_client_secret="secret",
        google_developer_token="DEV-TOKEN",
        oauth_redirect_uri="http://localhost:8000/oauth/google/callback",
    )


def _client():
    settings = _settings()
    # StaticPool: one shared in-memory connection so the test thread and the
    # TestClient's worker thread see the same database.
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


def test_oauth_start_redirects_and_persists_state():
    client, Session, _ = _client()
    r = client.get("/oauth/google/start", follow_redirects=False)
    assert r.status_code == 307 or r.status_code == 302
    assert "accounts.google.com" in r.headers["location"]
    from app.models import OAuthState
    with Session() as s:
        assert s.query(OAuthState).count() == 1


def test_oauth_callback_persists_token_and_consumes_state(monkeypatch):
    client, Session, settings = _client()

    # Begin the flow to create a state row.
    client.get("/oauth/google/start", follow_redirects=False)
    from app.models import OAuthState
    with Session() as s:
        state_row = s.query(OAuthState).one()
        state = state_row.state

    monkeypatch.setattr(oauth_mod, "exchange_code",
                        lambda settings, code, code_verifier: {"refresh_token": "rtok"})
    # Avoid a real Ads API call when listing accessible customers.
    import app.routes.auth_routes as ar
    monkeypatch.setattr(ar, "list_accessible_customers", lambda settings, refresh_token: ["1234567890"])

    r = client.get(f"/oauth/google/callback?code=abc&state={state}", follow_redirects=False)
    assert r.status_code == 200
    body = r.json()
    assert body["accessible_customers"] == ["1234567890"]

    with Session() as s:
        conn = s.query(Connection).one()
        assert conn.refresh_token is not None and conn.refresh_token != b"rtok"
        assert s.query(OAuthState).count() == 0  # consumed

    # Replay the same state -> rejected.
    r2 = client.get(f"/oauth/google/callback?code=abc&state={state}", follow_redirects=False)
    assert r2.status_code == 400


def test_summary_resolves_per_user_and_blocks_cross_tenant(monkeypatch):
    client, Session, settings = _client()

    # Seed two users, each with a connection holding a refresh token.
    from app.crypto import Crypto
    crypto = Crypto(settings.fernet_keys)
    with Session() as s:
        ua, ub = User(id="ua"), User(id="ub")
        s.add_all([ua, ub])
        s.flush()
        ct, ver = crypto.encrypt("tok-a")
        ca = Connection(user_id="ua", customer_id="1111111111", refresh_token=ct, token_version=ver)
        ct2, ver2 = crypto.encrypt("tok-b")
        cb = Connection(user_id="ub", customer_id="2222222222", refresh_token=ct2, token_version=ver2)
        s.add_all([ca, cb])
        s.commit()
        ca_id, cb_id = ca.id, cb.id

    # Stub the actual Ads read: echo the resolved provider's dev token + customer.
    import app.routes.account_routes as ac

    def fake_summary(provider, customer_id):
        return {"developer_token": provider.get_developer_token(), "customer_id": customer_id}

    monkeypatch.setattr(ac, "run_account_summary", fake_summary)

    # User A reading their own connection works.
    r = client.get(f"/accounts/{ca_id}/summary", headers={"X-Dev-User": "ua"})
    assert r.status_code == 200
    assert r.json()["customer_id"] == "1111111111"

    # User A reading user B's connection is blocked (IDOR -> 404).
    r2 = client.get(f"/accounts/{cb_id}/summary", headers={"X-Dev-User": "ua"})
    assert r2.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd webapp && python -m pytest tests/test_api.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.main'`.

- [ ] **Step 3: Implement the auth routes**

Create empty `webapp/app/routes/__init__.py`. Create `webapp/app/routes/auth_routes.py`:

```python
"""Web OAuth start + callback."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import oauth
from app.config import Settings, get_settings
from app.crypto import Crypto
from app.db import get_session
from app.identity import get_current_user
from app.models import Connection, OAuthState, User
from app.tokenstore_db import DbTokenStore

router = APIRouter()

STATE_TTL_SECONDS = 600


def list_accessible_customers(settings: Settings, refresh_token: str) -> list[str]:
    """Resolve the customer IDs the granted identity can access. Network call;
    mocked in tests. Implemented via the toolkit's client."""
    import gads_authflow
    from google.ads.googleads.client import GoogleAdsClient

    backend = gads_authflow.OAuthClientBackend({
        "refresh_token": refresh_token,
        "client_id": settings.google_oauth_client_id,
        "client_secret": settings.google_oauth_client_secret,
    })
    client = GoogleAdsClient.load_from_dict({
        "developer_token": settings.google_developer_token,
        "use_proto_plus": True,
        "credentials": backend.credentials(),
    })
    svc = client.get_service("CustomerService")
    res = svc.list_accessible_customers()
    return [name.split("/")[-1] for name in res.resource_names]


@router.get("/oauth/google/start")
def oauth_start(
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
):
    verifier, challenge = oauth.make_pkce()
    state = oauth.new_state()
    session.add(OAuthState(
        state=state,
        user_id=user.id,
        code_verifier=verifier,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=STATE_TTL_SECONDS),
    ))
    session.commit()
    return RedirectResponse(
        oauth.build_authorization_url(settings, state=state, code_challenge=challenge),
        status_code=302,
    )


@router.get("/oauth/google/callback")
def oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
):
    row = session.get(OAuthState, state)
    now = datetime.now(timezone.utc)
    if row is None or row.user_id != user.id or row.expires_at < now:
        raise HTTPException(status_code=400, detail="invalid or expired state")
    verifier = row.code_verifier
    session.delete(row)          # single-use
    session.commit()

    try:
        token = oauth.exchange_code(settings, code=code, code_verifier=verifier)
    except Exception:
        raise HTTPException(status_code=502, detail="token exchange failed")
    refresh_token = token.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=502, detail="no refresh token returned")

    customers = list_accessible_customers(settings, refresh_token)

    conn = Connection(
        user_id=user.id,
        scopes=oauth.ADWORDS_SCOPE,
        customer_id=customers[0] if customers else None,
        accessible_customers=customers,
    )
    session.add(conn)
    session.commit()

    store = DbTokenStore(session, Crypto(settings.fernet_keys), settings)
    store.set(conn.id, {"refresh_token": refresh_token})

    return JSONResponse({"connection_id": conn.id, "accessible_customers": customers})
```

- [ ] **Step 4: Implement the account routes**

Create `webapp/app/routes/account_routes.py`:

```python
"""Account listing, selection, and the proof-of-life summary endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.crypto import Crypto
from app.db import get_session
from app.identity import get_current_user
from app.models import Connection, User
from app.providers import ConnectionAuthError, WebCredentialProvider
from app.tokenstore_db import DbTokenStore

router = APIRouter()


def _owned_connection(session: Session, user: User, connection_id: str) -> Connection:
    conn = session.get(Connection, connection_id)
    if conn is None or conn.user_id != user.id:
        raise HTTPException(status_code=404, detail="connection not found")
    return conn


def run_account_summary(provider: WebCredentialProvider, customer_id: str) -> dict:
    """Execute one read path through the bound provider. Network call; the test
    overrides this. Uses the toolkit's client under the active provider."""
    import gads_client

    query = (
        "SELECT customer.id, customer.descriptive_name, customer.currency_code "
        "FROM customer LIMIT 1"
    )
    rows = gads_client.search_stream(customer_id, query)
    return {"customer_id": customer_id, "rows": rows}


@router.get("/accounts")
def list_accounts(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    conns = session.query(Connection).filter(Connection.user_id == user.id).all()
    return {
        "connections": [
            {
                "connection_id": c.id,
                "google_email": c.google_email,
                "customer_id": c.customer_id,
                "accessible_customers": c.accessible_customers or [],
            }
            for c in conns
        ]
    }


@router.post("/accounts/{connection_id}/select")
def select_customer(
    connection_id: str,
    customer_id: str = Body(..., embed=True),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    conn = _owned_connection(session, user, connection_id)
    allowed = conn.accessible_customers or []
    if allowed and customer_id not in allowed:
        raise HTTPException(status_code=400, detail="customer not accessible")
    conn.customer_id = customer_id
    session.commit()
    return {"connection_id": conn.id, "customer_id": conn.customer_id}


@router.get("/accounts/{connection_id}/summary")
def account_summary(
    connection_id: str,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
):
    import gads_provider

    conn = _owned_connection(session, user, connection_id)
    if not conn.customer_id:
        raise HTTPException(status_code=409, detail="no customer selected")
    store = DbTokenStore(session, Crypto(settings.fernet_keys), settings)
    provider = WebCredentialProvider(store, settings, conn)
    try:
        with gads_provider.bind_provider(provider):
            return run_account_summary(provider, conn.customer_id)
    except ConnectionAuthError:
        raise HTTPException(status_code=409, detail="reconnect required")
```

- [ ] **Step 5: Implement the app factory**

Create `webapp/app/main.py`:

```python
"""FastAPI app factory."""

from __future__ import annotations

from fastapi import FastAPI

from app.routes import account_routes, auth_routes


def create_app() -> FastAPI:
    app = FastAPI(title="Google Ads Agents - web backend")
    app.include_router(auth_routes.router)
    app.include_router(account_routes.router)
    return app


app = create_app()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd webapp && python -m pytest tests/test_api.py -q`
Expected: PASS (4 passed).

- [ ] **Step 7: Run the whole webapp suite**

Run: `cd webapp && python -m pytest -q`
Expected: PASS — all webapp tests green (config, crypto, models, tokenstore, providers, identity, oauth, api).

- [ ] **Step 8: Commit**

```bash
git add webapp/app/main.py webapp/app/routes/ webapp/tests/test_api.py
git commit -m "add app factory, oauth routes, and account routes with isolation test"
```

---

### Task 10: Alembic migrations and webapp README

**Files:**
- Create: `webapp/alembic.ini`
- Create: `webapp/alembic/env.py`
- Create: `webapp/alembic/script.py.mako`
- Create: `webapp/alembic/versions/0001_initial.py`
- Create: `webapp/README.md`

Tests build the schema with `create_all` (Task 4). Production uses Alembic. This task adds the migration scaffolding and an explicit initial migration matching the models, plus run docs.

- [ ] **Step 1: Create the Alembic config**

Create `webapp/alembic.ini`:

```ini
[alembic]
script_location = alembic
sqlalchemy.url = sqlite:///./alembic_dev.db

[loggers]
keys = root

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
```

The runtime URL is overridden from `DATABASE_URL` in `env.py`.

- [ ] **Step 2: Create the Alembic env**

Create `webapp/alembic/env.py`:

```python
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models import Base  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", os.environ.get("DATABASE_URL", config.get_main_option("sqlalchemy.url")))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"),
                      target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.", poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

Create `webapp/alembic/script.py.mako`:

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 3: Create the initial migration**

Create `webapp/alembic/versions/0001_initial.py`:

```python
"""initial schema

Revision ID: 0001
Revises:
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_JSON_LIST = JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(320), unique=True, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "connections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), index=True, nullable=False),
        sa.Column("google_email", sa.String(320), nullable=True),
        sa.Column("refresh_token", sa.LargeBinary, nullable=True),
        sa.Column("token_version", sa.Integer, nullable=True),
        sa.Column("customer_id", sa.String(16), nullable=True),
        sa.Column("login_customer_id", sa.String(16), nullable=True),
        sa.Column("accessible_customers", _JSON_LIST, nullable=True),
        sa.Column("scopes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "oauth_states",
        sa.Column("state", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), index=True, nullable=False),
        sa.Column("code_verifier", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("oauth_states")
    op.drop_table("connections")
    op.drop_table("users")
```

- [ ] **Step 4: Verify the migration applies**

Run: `cd webapp && DATABASE_URL="sqlite:///./alembic_check.db" python -m alembic upgrade head`
Expected: `Running upgrade  -> 0001, initial schema` and no error. Then clean up: `rm -f webapp/alembic_check.db`.

(On Windows PowerShell: `$env:DATABASE_URL="sqlite:///./alembic_check.db"; python -m alembic upgrade head` from the `webapp` directory, then `Remove-Item alembic_check.db`.)

- [ ] **Step 5: Write the webapp README**

Create `webapp/README.md`:

```markdown
# webapp — multi-tenant backend

FastAPI backend that resolves Google Ads credentials per user from an encrypted
Postgres store, with a web OAuth redirect flow. First slice of the web-app
trajectory; see `../docs/superpowers/specs/2026-05-30-webapp-backend-foundation-design.md`.

## Run locally

```
pip install -r requirements.txt
export DATABASE_URL=postgresql+psycopg2://user:pass@localhost/gads
export FERNET_KEYS='["<fernet-key>"]'           # python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
export GOOGLE_OAUTH_CLIENT_ID=...               # app Web OAuth client
export GOOGLE_OAUTH_CLIENT_SECRET=...
export GOOGLE_DEVELOPER_TOKEN=...               # app-owned, standard access
export OAUTH_REDIRECT_URI=http://localhost:8000/oauth/google/callback

python -m alembic upgrade head
uvicorn app.main:app --reload
```

## Endpoints

- `GET /oauth/google/start` — begin the OAuth grant (302 to Google).
- `GET /oauth/google/callback` — store the encrypted refresh token, list accessible customers.
- `GET /accounts` — list the current user's connections.
- `POST /accounts/{id}/select` — choose the active customer.
- `GET /accounts/{id}/summary` — proof-of-life read through the per-user provider.

Identity is stubbed (`X-Dev-User` header → seeded user). Real sign-in is a later sub-project.

## Tests

```
cd webapp
python -m pytest -q
```
```

- [ ] **Step 6: Commit**

```bash
git add webapp/alembic.ini webapp/alembic/ webapp/README.md
git commit -m "add alembic migrations and webapp readme"
```

---

## Final verification

- [ ] **Run the webapp suite**

Run: `cd webapp && python -m pytest -q`
Expected: all webapp tests pass.

- [ ] **Run the CLI suite (regression)**

Run: `cd scripts && python -m pytest -q`
Expected: 157 passed (154 prior + 3 from Task 1). CLI behavior unchanged.

- [ ] **Lint**

Run: `cd "C:/Program Data/Repository/google-ads-agents" && python -m ruff check scripts/gads_provider.py scripts/gads_client.py webapp`
Expected: no errors in the new files (pre-existing unrelated findings elsewhere are out of scope).

- [ ] **Update the root CHANGELOG**

Add a `0.7.0` entry to `CHANGELOG.md` summarizing the webapp backend foundation (provider seam, FastAPI webapp, DbTokenStore, web OAuth flow), and bump the test-count mention if you keep one. Commit:

```bash
git add CHANGELOG.md
git commit -m "changelog: web app backend foundation"
```

---

## Self-review notes (author)

- **Spec coverage:** provider seam (Task 1), config (2), crypto (3), models incl. all three tables (4), DbTokenStore (5), WebCredentialProvider + ConnectionAuthError (6), identity stub (7), OAuth+PKCE+state (8, 9), API incl. `/summary` proof-of-life and cross-tenant isolation (9), config/error handling (2, 9), testing incl. CLI regression (final), Alembic (10). The spec's "24h cap CLI-only" is honored by `WebCredentialProvider` never calling `enforce_session()`.
- **Open question resolved:** tests on SQLite via portable variant types; prod on Postgres via Alembic.
- **Deferred (out of scope, per spec):** real app auth replaces `identity.py`; the single read endpoint generalizes into the full API; many-connections-per-user; Google standard-access approval (operational).
- **Type consistency:** `Crypto.encrypt -> (bytes, int)`; `DbTokenStore(session, crypto, settings)`; `WebCredentialProvider(store, settings, connection)`; `bind_provider(provider)`; `resolve_user(session, settings, dev_user_header)`. These signatures are used identically across tasks.

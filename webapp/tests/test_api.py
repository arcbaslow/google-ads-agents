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

from datetime import datetime, timedelta, timezone  # noqa: E402

import app.oauth as oauth_mod  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db import get_session  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.models import Base, Connection, OAuthState, User  # noqa: E402
from app.main import create_app  # noqa: E402


def _settings():
    return Settings(
        database_url="sqlite://",
        fernet_keys=[Fernet.generate_key().decode()],
        google_oauth_client_id="cid",
        google_oauth_client_secret="secret",
        google_developer_token="DEV-TOKEN",
        oauth_redirect_uri="http://localhost:8000/oauth/google/callback",
        signin_redirect_uri="http://localhost:8000/auth/google/callback",
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


def test_oauth_start_redirects_and_persists_state():
    client, Session, settings = _client()
    _signin(client, Session, settings)
    r = client.get("/oauth/google/start", follow_redirects=False)
    assert r.status_code == 307 or r.status_code == 302
    assert "accounts.google.com" in r.headers["location"]
    from app.models import OAuthState
    with Session() as s:
        row = s.query(OAuthState).one()
        assert row.user_id == "ua"


def test_oauth_callback_persists_token_and_consumes_state(monkeypatch):
    client, Session, settings = _client()
    _signin(client, Session, settings)

    # Begin the flow to create a state row.
    client.get("/oauth/google/start", follow_redirects=False)
    from app.models import OAuthState
    with Session() as s:
        state_row = s.query(OAuthState).one()
        state = state_row.state

    monkeypatch.setattr(oauth_mod, "exchange_code",
                        lambda settings, code, code_verifier: {"refresh_token": "rtok",
                                                               "id_token": "idtok"})
    monkeypatch.setattr(oauth_mod, "verify_id_token",
                        lambda settings, raw: {"email": "user@goodlabs.kz"})
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
        assert conn.google_email == "user@goodlabs.kz"
        assert s.query(OAuthState).count() == 0  # consumed

    # Replay the same state -> rejected.
    r2 = client.get(f"/oauth/google/callback?code=abc&state={state}", follow_redirects=False)
    assert r2.status_code == 400


def test_select_rejects_customer_when_accessible_list_unknown():
    client, Session, settings = _client()
    _signin(client, Session, settings, user_id="ua")
    with Session() as s:
        conn = Connection(user_id="ua", accessible_customers=None)
        s.add(conn)
        s.commit()
        conn_id = conn.id

    r = client.post(f"/accounts/{conn_id}/select", json={"customer_id": "9999999999"})
    assert r.status_code == 400

    with Session() as s:
        assert s.get(Connection, conn_id).customer_id is None


def test_oauth_callback_denied_returns_400_and_consumes_state():
    client, Session, settings = _client()
    _signin(client, Session, settings)

    client.get("/oauth/google/start", follow_redirects=False)
    from app.models import OAuthState
    with Session() as s:
        state = s.query(OAuthState).one().state

    r = client.get(
        f"/oauth/google/callback?error=access_denied&state={state}",
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "access_denied" in r.json()["detail"]

    with Session() as s:
        assert s.query(OAuthState).count() == 0  # consumed


def test_oauth_callback_persists_token_when_listing_fails(monkeypatch):
    client, Session, settings = _client()
    _signin(client, Session, settings)

    client.get("/oauth/google/start", follow_redirects=False)
    from app.models import OAuthState
    with Session() as s:
        state = s.query(OAuthState).one().state

    monkeypatch.setattr(oauth_mod, "exchange_code",
                        lambda settings, code, code_verifier: {"refresh_token": "rtok",
                                                               "id_token": "idtok"})
    monkeypatch.setattr(oauth_mod, "verify_id_token",
                        lambda settings, raw: {"email": "user@goodlabs.kz"})
    import app.routes.auth_routes as ar

    def boom(settings, refresh_token):
        raise RuntimeError("ads api unavailable")

    monkeypatch.setattr(ar, "list_accessible_customers", boom)

    r = client.get(f"/oauth/google/callback?code=abc&state={state}", follow_redirects=False)
    assert r.status_code == 200
    body = r.json()
    assert body["accessible_customers"] == []
    assert "warning" in body

    # The granted refresh token survives the listing failure.
    with Session() as s:
        conn = s.query(Connection).one()
        assert conn.refresh_token is not None


def test_oauth_callback_rejects_missing_or_invalid_id_token(monkeypatch):
    client, Session, settings = _client()
    _signin(client, Session, settings)
    from app.models import OAuthState

    def start():
        client.get("/oauth/google/start", follow_redirects=False)
        with Session() as s:
            return s.query(OAuthState).one().state

    # No id_token in the exchange response.
    state = start()
    monkeypatch.setattr(oauth_mod, "exchange_code",
                        lambda settings, code, code_verifier: {"refresh_token": "rtok"})
    r = client.get(f"/oauth/google/callback?code=abc&state={state}", follow_redirects=False)
    assert r.status_code == 502

    # id_token present but verification fails.
    state = start()
    monkeypatch.setattr(oauth_mod, "exchange_code",
                        lambda settings, code, code_verifier: {"refresh_token": "rtok",
                                                               "id_token": "bad"})

    def reject(settings, raw):
        raise ValueError("bad signature")

    monkeypatch.setattr(oauth_mod, "verify_id_token", reject)
    r2 = client.get(f"/oauth/google/callback?code=abc&state={state}", follow_redirects=False)
    assert r2.status_code == 502

    # No connection row was created for an unverified identity.
    with Session() as s:
        assert s.query(Connection).count() == 0


def _seed_connection(Session, settings, user_id="ua", token="tok-a"):
    from app.crypto import Crypto
    crypto = Crypto(settings.fernet_keys)
    with Session() as s:
        if s.get(User, user_id) is None:
            s.add(User(id=user_id))
            s.flush()
        ct, ver = crypto.encrypt(token)
        conn = Connection(user_id=user_id, customer_id="1111111111",
                          refresh_token=ct, token_version=ver)
        s.add(conn)
        s.commit()
        return conn.id


def test_disconnect_revokes_and_clears_token(monkeypatch):
    client, Session, settings = _client()
    conn_id = _seed_connection(Session, settings)
    _signin(client, Session, settings, user_id="ua")

    revoked_with = []
    monkeypatch.setattr(oauth_mod, "revoke_token",
                        lambda token: revoked_with.append(token) or True)

    r = client.post(f"/accounts/{conn_id}/disconnect")
    assert r.status_code == 200
    assert r.json()["revoked"] is True
    assert revoked_with == ["tok-a"]

    with Session() as s:
        conn = s.get(Connection, conn_id)
        assert conn.refresh_token is None
        assert conn.token_version is None
        assert conn.revoked_at is not None


def test_disconnect_blocks_cross_tenant():
    client, Session, settings = _client()
    conn_id = _seed_connection(Session, settings, user_id="ua")
    _signin(client, Session, settings, user_id="ub")

    r = client.post(f"/accounts/{conn_id}/disconnect")
    assert r.status_code == 404
    assert r.json()["detail"] == "connection not found"

    with Session() as s:
        assert s.get(Connection, conn_id).refresh_token is not None


def test_disconnect_clears_locally_when_revocation_fails(monkeypatch):
    client, Session, settings = _client()
    conn_id = _seed_connection(Session, settings)
    _signin(client, Session, settings, user_id="ua")

    def boom(token):
        raise OSError("network down")

    monkeypatch.setattr(oauth_mod, "revoke_token", boom)

    r = client.post(f"/accounts/{conn_id}/disconnect")
    assert r.status_code == 200
    assert r.json()["revoked"] is False

    with Session() as s:
        assert s.get(Connection, conn_id).refresh_token is None


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
        ca_id = ca.id

    # Stub the actual Ads read: echo the resolved provider's dev token + customer.
    import app.routes.account_routes as ac

    def fake_summary(provider, customer_id):
        return {"developer_token": provider.get_developer_token(), "customer_id": customer_id}

    monkeypatch.setattr(ac, "run_account_summary", fake_summary)

    # User A reading their own connection works.
    _signin(client, Session, settings, user_id="ua")
    r = client.get(f"/accounts/{ca_id}/summary")
    assert r.status_code == 200
    assert r.json()["customer_id"] == "1111111111"

    # User B probing user A's connection is blocked (IDOR -> 404).
    _signin(client, Session, settings, user_id="ub")
    r2 = client.get(f"/accounts/{ca_id}/summary")
    assert r2.status_code == 404


def test_accounts_requires_signin():
    client, Session, settings = _client()
    r = client.get("/accounts")
    assert r.status_code == 401


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

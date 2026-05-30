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

import app.oauth as oauth_mod  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db import get_session  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.models import Base, Connection, User  # noqa: E402
from app.main import create_app  # noqa: E402


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

import os
import sys

import pytest

# Make the toolkit (scripts/) importable for OAuthClientBackend reuse.
SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from app.models import Connection, User  # noqa: E402
from app.providers import ConnectionAuthError, WebCredentialProvider  # noqa: E402
from app.tokenstore_db import DbTokenStore  # noqa: E402
from app.crypto import Crypto  # noqa: E402


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

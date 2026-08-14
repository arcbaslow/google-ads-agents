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

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

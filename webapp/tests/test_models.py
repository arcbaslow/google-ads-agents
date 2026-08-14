from datetime import datetime, timezone

import pytest
from app.models import Connection, OAuthState, User, UserSession
from sqlalchemy.exc import IntegrityError


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


def test_session_token_hash_unique(session):
    u = User(email="t@example.com")
    session.add(u)
    session.flush()
    session.add(UserSession(user_id=u.id, token_hash="cd" * 32,
                            expires_at=datetime.now(timezone.utc)))
    session.commit()
    session.add(UserSession(user_id=u.id, token_hash="cd" * 32,
                            expires_at=datetime.now(timezone.utc)))
    with pytest.raises(IntegrityError):
        session.commit()

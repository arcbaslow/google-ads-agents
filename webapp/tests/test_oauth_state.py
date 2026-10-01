from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest
from app.models import Base, OAuthState, User
from app.oauth_state import consume_state
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.mark.parametrize("purpose,user_id", [("signin", None), ("connect", "owner")])
def test_only_one_concurrent_consumer_gets_verifier(tmp_path, purpose, user_id):
    engine = create_engine(f"sqlite:///{tmp_path / 'oauth-test.sqlite'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    with sessions() as db:
        db.add(User(id="owner"))
        db.add(OAuthState(state="state", purpose=purpose, user_id=user_id,
                          code_verifier="verifier",
                          expires_at=datetime.now(timezone.utc) + timedelta(minutes=5)))
        db.commit()
    barrier = Barrier(2, timeout=10)

    def consume():
        with sessions() as db:
            barrier.wait()
            return consume_state(db, "state", purpose, user_id)

    try:
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: consume(), range(2)))
        assert results.count("verifier") == 1
        assert results.count(None) == 1
    finally:
        engine.dispose()


def test_wrong_owner_or_purpose_cannot_consume_state(session):
    session.add(User(id="owner"))
    session.add(OAuthState(state="state", purpose="connect", user_id="owner",
                           code_verifier="v",
                           expires_at=datetime.now(timezone.utc) + timedelta(minutes=5)))
    session.commit()
    assert consume_state(session, "state", "connect", "other") is None
    assert consume_state(session, "state", "signin", None) is None
    assert consume_state(session, "state", "connect", "owner") == "v"


def test_expired_state_is_consumed_without_returning_verifier(session):
    session.add(OAuthState(state="old", purpose="signin", code_verifier="v",
                           expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
    session.commit()
    assert consume_state(session, "old", "signin", None) is None
    assert session.get(OAuthState, "old") is None

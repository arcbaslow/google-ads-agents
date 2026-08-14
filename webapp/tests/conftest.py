import pytest
from app.config import Settings, get_settings
from app.db import get_session
from app.main import create_app
from app.models import Base
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


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
def settings():
    return _make_settings()


@pytest.fixture
def make_api():
    def make(**settings_over):
        settings = _make_settings(**settings_over)
        # StaticPool: one shared in-memory connection so the test thread and
        # the TestClient's worker thread see the same database.
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


@pytest.fixture
def session(settings):
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine, future=True)
    with Session() as s:
        yield s

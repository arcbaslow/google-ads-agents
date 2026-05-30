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

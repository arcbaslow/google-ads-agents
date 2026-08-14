import pytest
from app.config import Settings
from cryptography.fernet import Fernet


def _env(**over):
    base = dict(
        DATABASE_URL="sqlite://",
        FERNET_KEYS=f'["{Fernet.generate_key().decode()}"]',
        GOOGLE_OAUTH_CLIENT_ID="cid",
        GOOGLE_OAUTH_CLIENT_SECRET="secret",
        GOOGLE_DEVELOPER_TOKEN="dev",
        OAUTH_REDIRECT_URI="http://localhost:8000/oauth/google/callback",
        SIGNIN_REDIRECT_URI="http://localhost:8000/auth/google/callback",
    )
    base.update(over)
    return base


def test_settings_load_from_env(monkeypatch):
    for k, v in _env().items():
        monkeypatch.setenv(k, v)
    s = Settings()
    assert s.google_developer_token == "dev"
    assert len(s.fernet_keys) == 1
    assert s.signin_redirect_uri == "http://localhost:8000/auth/google/callback"
    assert s.allowed_signins == []
    assert s.session_max_hours == 24
    assert s.cookie_secure is True


def test_missing_required_raises(monkeypatch):
    for k in ("DATABASE_URL", "FERNET_KEYS", "GOOGLE_OAUTH_CLIENT_ID",
              "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_DEVELOPER_TOKEN",
              "OAUTH_REDIRECT_URI", "SIGNIN_REDIRECT_URI"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(Exception):
        Settings()

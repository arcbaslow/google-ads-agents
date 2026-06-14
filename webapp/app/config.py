"""Typed settings from env. Fail fast on missing required values at startup."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    fernet_keys: list[str]                 # oldest first, newest last (append-only)
    google_oauth_client_id: str
    google_oauth_client_secret: str
    google_developer_token: str
    oauth_redirect_uri: str
    signin_redirect_uri: str
    allowed_signins: list[str] = []     # email domains or full emails; empty = anyone
    session_max_hours: int = 24
    cookie_secure: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()

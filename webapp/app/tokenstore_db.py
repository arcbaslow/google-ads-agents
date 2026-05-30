"""DbTokenStore: TokenStore backed by the connections table.

Only the per-user refresh token is stored (encrypted). client_id/client_secret
come from app config, so the record handed to OAuthClientBackend matches the
LocalFileTokenStore shape and the backend needs no change.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.crypto import Crypto
from app.models import Connection


class DbTokenStore:
    def __init__(self, session: Session, crypto: Crypto, settings: Settings):
        self._session = session
        self._crypto = crypto
        self._settings = settings

    def get(self, key: str) -> dict[str, Any] | None:
        conn = self._session.get(Connection, key)
        if not conn or conn.refresh_token is None or conn.token_version is None:
            return None
        return {
            "refresh_token": self._crypto.decrypt(conn.refresh_token, conn.token_version),
            "client_id": self._settings.google_oauth_client_id,
            "client_secret": self._settings.google_oauth_client_secret,
        }

    def set(self, key: str, record: dict[str, Any]) -> None:
        conn = self._session.get(Connection, key)
        if conn is None:
            raise KeyError(f"connection {key!r} does not exist")
        if "refresh_token" in record:
            ct, ver = self._crypto.encrypt(record["refresh_token"])
            conn.refresh_token = ct
            conn.token_version = ver
        self._session.commit()

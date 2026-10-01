"""WebCredentialProvider: per-request credential resolution for a connection.

Reuses the 0.6.0 OAuthClientBackend to refresh credentials from the stored
record. No 24h session cap here - that is a CLI-local concern.
"""

from __future__ import annotations

from typing import Any

from app.config import Settings
from app.models import Connection
from app.tokenstore_db import DbTokenStore


class ConnectionAuthError(RuntimeError):
    """The connection has no usable refresh token; the user must reconnect."""


class WebCredentialProvider:
    def __init__(self, store: DbTokenStore, settings: Settings, connection: Connection):
        self._store = store
        self._settings = settings
        self._connection = connection

    def get_credentials(self) -> Any:
        import gads_authflow
        from google.auth.exceptions import RefreshError

        record = self._store.get(self._connection.id)
        if not record:
            raise ConnectionAuthError(
                f"connection {self._connection.id} has no stored refresh token"
            )
        try:
            return gads_authflow.OAuthClientBackend(record).credentials()
        except RefreshError as exc:
            # Transient refresh failures are not evidence of a revoked grant.
            if exc.retryable:
                raise
            raise ConnectionAuthError("Google authorization expired; reconnect required") from None

    def get_developer_token(self) -> str | None:
        return self._settings.google_developer_token

    def get_login_customer_id(self) -> str | None:
        return self._connection.login_customer_id

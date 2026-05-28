"""Auth backends.

Credential resolution dispatches on a profile's auth_method so a restricted
Workspace user can use their own OAuth client instead of gcloud ADC. Every
downstream script is unaffected: gads_client.build_client() calls
gads_auth.get_credentials(), which routes here.
"""

from __future__ import annotations

from typing import Any, Protocol

import gads_auth

TOKEN_URI = "https://oauth2.googleapis.com/token"


class AuthBackend(Protocol):
    def credentials(self) -> Any: ...


class GcloudAdcBackend:
    """The original path: gcloud Application Default Credentials."""

    def credentials(self) -> Any:
        import google.auth

        creds, _project = google.auth.default(scopes=[gads_auth.ADWORDS])
        return creds


class OAuthClientBackend:
    """User-owned OAuth client: build Credentials from a stored refresh token."""

    def __init__(self, record: dict[str, Any]):
        self._record = record

    def credentials(self) -> Any:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        creds = Credentials(
            token=None,
            refresh_token=self._record["refresh_token"],
            client_id=self._record["client_id"],
            client_secret=self._record["client_secret"],
            token_uri=TOKEN_URI,
            scopes=[gads_auth.ADWORDS],
        )
        creds.refresh(Request())
        return creds


def select_backend(profile_name: str | None, profile: dict[str, Any], store=None) -> AuthBackend:
    method = (profile or {}).get("auth_method", "gcloud_adc")
    if method == "oauth_client":
        if store is None:
            from gads_tokenstore import LocalFileTokenStore

            store = LocalFileTokenStore()
        record = store.get(profile_name)
        if not record:
            raise gads_auth.AuthRequiredError(
                f"Profile '{profile_name}' uses oauth_client but has no stored "
                f"refresh token. Run:\n  python scripts/gads_auth.py --oauth-login "
                f"--client-secrets client_secret.json"
            )
        return OAuthClientBackend(record)
    return GcloudAdcBackend()

"""OAuth helpers: PKCE, the Google authorization URL, and code exchange.

The web flow uses the app-owned Web client (config), the restricted `adwords`
scope, offline access + forced consent (to obtain a refresh token), and PKCE.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import urlencode

from app.config import Settings

ADWORDS_SCOPE = "https://www.googleapis.com/auth/adwords"
OPENID_SCOPES = ["openid", "email"]
AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def make_pkce() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


def new_state() -> str:
    return secrets.token_urlsafe(32)


def build_authorization_url(settings: Settings, state: str, code_challenge: str) -> str:
    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": settings.oauth_redirect_uri,
        "response_type": "code",
        "scope": " ".join([ADWORDS_SCOPE, *OPENID_SCOPES]),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


def revoke_token(token: str) -> bool:
    """Revoke a refresh token at Google. Returns True when Google confirmed.
    Network call; mocked in tests."""
    import requests

    resp = requests.post(REVOKE_ENDPOINT, data={"token": token}, timeout=30)
    return resp.status_code == 200


def verify_id_token(settings: Settings, raw_id_token: str) -> dict:
    """Validate the ID token (signature, audience, expiry) against Google's
    certs and return its claims. Raises ValueError on failure. Network call
    (cert fetch); mocked in tests."""
    from google.auth.transport.requests import Request
    from google.oauth2 import id_token as google_id_token

    return google_id_token.verify_oauth2_token(
        raw_id_token, Request(), audience=settings.google_oauth_client_id
    )


def exchange_code(settings: Settings, code: str, code_verifier: str) -> dict:
    """Exchange an authorization code for tokens. Returns the token response dict
    with at least `refresh_token`. Network call; mocked in tests."""
    import requests

    resp = requests.post(
        TOKEN_ENDPOINT,
        data={
            "client_id": settings.google_oauth_client_id,
            "client_secret": settings.google_oauth_client_secret,
            "code": code,
            "code_verifier": code_verifier,
            "grant_type": "authorization_code",
            "redirect_uri": settings.oauth_redirect_uri,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()

"""Google sign-in: OIDC start + callback, logout, and the /me probe."""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter

from app import oauth
from app.config import Settings

router = APIRouter()

STATE_TTL_SECONDS = 600
SIGNIN_SCOPES = ["openid", "email"]


def email_allowed(allowed: list[str], email: str) -> bool:
    """Entries with '@' match the full email; entries without match the
    email's domain exactly. Case-insensitive. Empty list allows anyone."""
    if not allowed:
        return True
    email = email.lower()
    domain = email.split("@", 1)[1] if "@" in email else ""
    for entry in allowed:
        entry = entry.lower()
        if "@" in entry:
            if entry == email:
                return True
        elif entry == domain:
            return True
    return False


def build_signin_url(settings: Settings, state: str, code_challenge: str) -> str:
    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": settings.signin_redirect_uri,
        "response_type": "code",
        "scope": " ".join(SIGNIN_SCOPES),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{oauth.AUTH_ENDPOINT}?{urlencode(params)}"

"""Same-origin enforcement for unsafe methods, on top of SameSite=Lax."""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import Depends, HTTPException, Request

from app.config import Settings, get_settings

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def app_origin(settings: Settings) -> str:
    u = urlparse(settings.signin_redirect_uri)
    return f"{u.scheme}://{u.netloc}"


def require_same_origin(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    if request.method in SAFE_METHODS:
        return
    origin = request.headers.get("origin")
    if origin is not None and origin != app_origin(settings):
        raise HTTPException(status_code=403, detail="cross-origin request rejected")

"""Google sign-in: OIDC start + callback, logout, and the /me probe."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import oauth, sessions
from app.config import Settings, get_settings
from app.db import get_session
from app.identity import SESSION_COOKIE
from app.models import OAuthState, User

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
        entry = entry.strip().lower()
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


@router.get("/auth/google/start")
def signin_start(
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_session),
):
    verifier, challenge = oauth.make_pkce()
    state = oauth.new_state()
    db.add(OAuthState(
        state=state,
        user_id=None,
        purpose="signin",
        code_verifier=verifier,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=STATE_TTL_SECONDS),
    ))
    db.commit()
    return RedirectResponse(build_signin_url(settings, state, challenge), status_code=302)


@router.get("/auth/google/callback")
def signin_callback(
    state: str = Query(...),
    code: str | None = Query(None),
    error: str | None = Query(None),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_session),
):
    row = db.get(OAuthState, state)
    if row is None or row.purpose != "signin":
        raise HTTPException(status_code=400, detail="invalid or expired state")
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        db.delete(row)
        db.commit()
        raise HTTPException(status_code=400, detail="invalid or expired state")
    verifier = row.code_verifier
    db.delete(row)          # single-use
    db.commit()

    if error:
        raise HTTPException(status_code=400, detail=f"authorization failed: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="missing code")

    try:
        token = oauth.exchange_code(settings, code=code, code_verifier=verifier,
                                    redirect_uri=settings.signin_redirect_uri)
    except Exception:
        raise HTTPException(status_code=502, detail="token exchange failed")
    raw_id_token = token.get("id_token")
    if not raw_id_token:
        raise HTTPException(status_code=502, detail="no id token returned")
    try:
        claims = oauth.verify_id_token(settings, raw_id_token)
    except ValueError:
        raise HTTPException(status_code=502, detail="id token verification failed")

    email = claims.get("email")
    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status_code=502, detail="id token missing subject")

    if not email or not claims.get("email_verified", False):
        raise HTTPException(status_code=403, detail="email not verified")
    if not email_allowed(settings.allowed_signins, email):
        raise HTTPException(status_code=403, detail="email not allowed")

    user = db.query(User).filter(User.google_sub == sub).one_or_none()
    if user is None:
        user = User(google_sub=sub, email=email)
        db.add(user)
        db.commit()
    elif user.email != email:
        user.email = email
        db.commit()

    token_value, session_row = sessions.create_session(
        db, user.id, settings.session_max_hours)
    resp = JSONResponse({
        "user": {"id": user.id, "email": user.email},
        "expires_at": session_row.expires_at.isoformat(),
    })
    resp.set_cookie(
        SESSION_COOKIE, token_value,
        max_age=settings.session_max_hours * 3600,
        httponly=True, secure=settings.cookie_secure, samesite="lax", path="/",
    )
    return resp

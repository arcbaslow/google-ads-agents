"""Web OAuth start + callback."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import oauth
from app.config import Settings, get_settings
from app.crypto import Crypto
from app.db import get_session
from app.identity import get_current_user
from app.models import Connection, OAuthState, User
from app.tokenstore_db import DbTokenStore

router = APIRouter()

STATE_TTL_SECONDS = 600


def list_accessible_customers(settings: Settings, refresh_token: str) -> list[str]:
    """Resolve the customer IDs the granted identity can access. Network call;
    mocked in tests. Implemented via the toolkit's client."""
    import gads_authflow
    from google.ads.googleads.client import GoogleAdsClient

    backend = gads_authflow.OAuthClientBackend({
        "refresh_token": refresh_token,
        "client_id": settings.google_oauth_client_id,
        "client_secret": settings.google_oauth_client_secret,
    })
    client = GoogleAdsClient.load_from_dict({
        "developer_token": settings.google_developer_token,
        "use_proto_plus": True,
        "credentials": backend.credentials(),
    })
    svc = client.get_service("CustomerService")
    res = svc.list_accessible_customers()
    return [name.split("/")[-1] for name in res.resource_names]


@router.get("/oauth/google/start")
def oauth_start(
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
):
    verifier, challenge = oauth.make_pkce()
    state = oauth.new_state()
    session.add(OAuthState(
        state=state,
        user_id=user.id,
        purpose="connect",
        code_verifier=verifier,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=STATE_TTL_SECONDS),
    ))
    session.commit()
    return RedirectResponse(
        oauth.build_authorization_url(settings, state=state, code_challenge=challenge),
        status_code=302,
    )


@router.get("/oauth/google/callback")
def oauth_callback(
    state: str = Query(...),
    code: str | None = Query(None),
    error: str | None = Query(None),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
):
    row = session.get(OAuthState, state)
    if row is None or row.user_id != user.id or row.purpose != "connect":
        raise HTTPException(status_code=400, detail="invalid or expired state")
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        session.delete(row)
        session.commit()
        raise HTTPException(status_code=400, detail="invalid or expired state")
    verifier = row.code_verifier
    session.delete(row)          # single-use
    session.commit()

    if error:
        raise HTTPException(status_code=400, detail=f"authorization failed: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="missing code")

    try:
        token = oauth.exchange_code(settings, code=code, code_verifier=verifier)
    except Exception:
        raise HTTPException(status_code=502, detail="token exchange failed")
    refresh_token = token.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=502, detail="no refresh token returned")
    raw_id_token = token.get("id_token")
    if not raw_id_token:
        raise HTTPException(status_code=502, detail="no id token returned")
    try:
        claims = oauth.verify_id_token(settings, raw_id_token)
    except ValueError:
        raise HTTPException(status_code=502, detail="id token verification failed")

    # Persist the granted token before the customer listing so a listing
    # failure does not force the user back through consent.
    conn = Connection(user_id=user.id, scopes=oauth.ADWORDS_SCOPE,
                      google_email=claims.get("email"))
    session.add(conn)
    session.commit()
    store = DbTokenStore(session, Crypto(settings.fernet_keys), settings)
    store.set(conn.id, {"refresh_token": refresh_token})

    warning = None
    try:
        customers = list_accessible_customers(settings, refresh_token)
    except Exception:
        customers = []
        warning = "failed to list accessible customers"
    conn.customer_id = customers[0] if customers else None
    conn.accessible_customers = customers
    session.commit()

    body: dict = {"connection_id": conn.id, "accessible_customers": customers}
    if warning:
        body["warning"] = warning
    return JSONResponse(body)

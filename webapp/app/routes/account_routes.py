"""Account listing, selection, and the proof-of-life summary endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.crypto import Crypto
from app.db import get_session
from app.identity import get_current_user
from app.models import Connection, User
from app.providers import ConnectionAuthError, WebCredentialProvider
from app.tokenstore_db import DbTokenStore

router = APIRouter()


def _owned_connection(session: Session, user: User, connection_id: str) -> Connection:
    conn = session.get(Connection, connection_id)
    if conn is None or conn.user_id != user.id:
        raise HTTPException(status_code=404, detail="connection not found")
    return conn


def run_account_summary(provider: WebCredentialProvider, customer_id: str) -> dict:
    """Execute one read path through the bound provider. Network call; the test
    overrides this. Uses the toolkit's client under the active provider."""
    import gads_client

    query = (
        "SELECT customer.id, customer.descriptive_name, customer.currency_code "
        "FROM customer LIMIT 1"
    )
    rows = gads_client.search_stream(customer_id, query)
    return {"customer_id": customer_id, "rows": rows}


@router.get("/accounts")
def list_accounts(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    conns = session.query(Connection).filter(Connection.user_id == user.id).all()
    return {
        "connections": [
            {
                "connection_id": c.id,
                "google_email": c.google_email,
                "customer_id": c.customer_id,
                "accessible_customers": c.accessible_customers or [],
            }
            for c in conns
        ]
    }


@router.post("/accounts/{connection_id}/select")
def select_customer(
    connection_id: str,
    customer_id: str = Body(..., embed=True),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    conn = _owned_connection(session, user, connection_id)
    allowed = conn.accessible_customers or []
    if allowed and customer_id not in allowed:
        raise HTTPException(status_code=400, detail="customer not accessible")
    conn.customer_id = customer_id
    session.commit()
    return {"connection_id": conn.id, "customer_id": conn.customer_id}


@router.get("/accounts/{connection_id}/summary")
def account_summary(
    connection_id: str,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
):
    import gads_provider

    conn = _owned_connection(session, user, connection_id)
    if not conn.customer_id:
        raise HTTPException(status_code=409, detail="no customer selected")
    store = DbTokenStore(session, Crypto(settings.fernet_keys), settings)
    provider = WebCredentialProvider(store, settings, conn)
    try:
        with gads_provider.bind_provider(provider):
            return run_account_summary(provider, conn.customer_id)
    except ConnectionAuthError:
        raise HTTPException(status_code=409, detail="reconnect required")

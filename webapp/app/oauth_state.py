"""Consume OAuth state once, including across concurrent database sessions."""

from datetime import datetime, timezone

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import OAuthState


def consume_state(db: Session, state: str, purpose: str, user_id: str | None) -> str | None:
    row = db.execute(
        delete(OAuthState).where(
            OAuthState.state == state,
            OAuthState.purpose == purpose,
            OAuthState.user_id == user_id,
        ).returning(OAuthState.code_verifier, OAuthState.expires_at)
    ).first()
    # The code must not be exchanged until the deletion is durable.
    db.commit()
    if row is None:
        return None
    expiry = row.expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if expiry <= datetime.now(timezone.utc):
        return None
    return row.code_verifier

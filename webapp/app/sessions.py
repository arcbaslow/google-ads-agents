"""DB-backed sessions: opaque tokens, sha256 at rest, absolute expiry."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import UserSession


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user_id: str, max_hours: int) -> tuple[str, UserSession]:
    token = secrets.token_urlsafe(32)
    row = UserSession(
        user_id=user_id,
        token_hash=_hash(token),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=max_hours),
    )
    db.add(row)
    db.commit()
    return token, row


def resolve_session(db: Session, token: str) -> UserSession | None:
    row = db.query(UserSession).filter(UserSession.token_hash == _hash(token)).one_or_none()
    if row is None:
        return None
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        db.delete(row)
        db.commit()
        return None
    return row


def delete_session(db: Session, token: str) -> None:
    row = db.query(UserSession).filter(UserSession.token_hash == _hash(token)).one_or_none()
    if row is not None:
        db.delete(row)
        db.commit()

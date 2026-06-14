"""Current-user resolution from the session cookie."""

from __future__ import annotations

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy.orm import Session

from app import sessions
from app.db import get_session
from app.models import User

SESSION_COOKIE = "gads_session"


def get_current_user(
    gads_session: str | None = Cookie(default=None),
    db: Session = Depends(get_session),
) -> User:
    if not gads_session:
        raise HTTPException(status_code=401, detail="not signed in")
    row = sessions.resolve_session(db, gads_session)
    if row is None:
        raise HTTPException(status_code=401, detail="not signed in")
    user = db.get(User, row.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="not signed in")
    return user

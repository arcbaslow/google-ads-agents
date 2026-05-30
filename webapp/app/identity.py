"""Current-user resolution. Stub for this slice; real sign-in replaces it.

resolve_user() is pure (takes a session) so it is unit-testable. get_current_user
is the FastAPI dependency wrapper.
"""

from __future__ import annotations

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.models import User


def resolve_user(session: Session, settings: Settings, dev_user_header: str | None) -> User:
    user_id = dev_user_header or settings.dev_user_id
    user = session.get(User, user_id)
    if user is None:
        user = User(id=user_id)
        session.add(user)
        session.commit()
    return user


def get_current_user(
    x_dev_user: str | None = Header(default=None),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> User:
    return resolve_user(session, settings, x_dev_user)

"""Engine/session wiring and the FastAPI session dependency."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import Base

_engine = None
_Session: sessionmaker | None = None


def _ensure() -> sessionmaker:
    global _engine, _Session
    if _Session is None:
        _engine = create_engine(get_settings().database_url, future=True)
        Base.metadata.create_all(_engine)  # dev/bootstrap; prod schema via Alembic
        _Session = sessionmaker(_engine, future=True)
    return _Session


def get_session() -> Iterator[Session]:
    factory = _ensure()
    with factory() as session:
        yield session

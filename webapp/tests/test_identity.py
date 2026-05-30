from app.identity import resolve_user
from app.models import User


def test_seeds_default_user_when_no_header(session, settings):
    u = resolve_user(session, settings, dev_user_header=None)
    assert isinstance(u, User)
    assert u.id == settings.dev_user_id
    # idempotent
    u2 = resolve_user(session, settings, dev_user_header=None)
    assert u2.id == u.id


def test_resolves_existing_user_by_header(session, settings):
    existing = User(id="abc123", email="a@example.com")
    session.add(existing)
    session.commit()
    u = resolve_user(session, settings, dev_user_header="abc123")
    assert u.id == "abc123"


def test_unknown_header_user_is_created(session, settings):
    u = resolve_user(session, settings, dev_user_header="newid")
    assert u.id == "newid"

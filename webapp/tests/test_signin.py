from urllib.parse import parse_qs, urlparse

from app.models import OAuthState
from app.routes.signin_routes import build_signin_url, email_allowed


def test_email_allowed_empty_list_allows_anyone():
    assert email_allowed([], "anyone@example.com")


def test_email_allowed_matches_domain_exactly():
    allowed = ["goodlabs.kz"]
    assert email_allowed(allowed, "dilshat@goodlabs.kz")
    assert email_allowed(allowed, "DILSHAT@GOODLABS.KZ")
    assert not email_allowed(allowed, "x@sub.goodlabs.kz")
    assert not email_allowed(allowed, "x@evil-goodlabs.kz")


def test_email_allowed_matches_full_email():
    allowed = ["dilshatrakhimov@gmail.com"]
    assert email_allowed(allowed, "dilshatrakhimov@gmail.com")
    assert not email_allowed(allowed, "other@gmail.com")


def test_signin_url_uses_identity_scopes_only(settings):
    url = build_signin_url(settings, state="S", code_challenge="C")
    q = parse_qs(urlparse(url).query)
    assert q["redirect_uri"] == [settings.signin_redirect_uri]
    assert "openid" in q["scope"][0]
    assert "adwords" not in q["scope"][0]
    assert "access_type" not in q          # no offline refresh token for sign-in
    assert q["code_challenge_method"] == ["S256"]
    assert q["state"] == ["S"]
    assert "prompt" not in q


def test_signin_start_redirects_with_signin_state(api):
    client, Session, settings = api
    r = client.get("/auth/google/start", follow_redirects=False)
    assert r.status_code == 302
    assert "accounts.google.com" in r.headers["location"]
    with Session() as s:
        row = s.query(OAuthState).one()
        assert row.purpose == "signin"
        assert row.user_id is None

from urllib.parse import parse_qs, urlparse

import app.oauth as oauth_mod
from app.models import OAuthState, User, UserSession
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


def _start_signin(client, Session):
    client.get("/auth/google/start", follow_redirects=False)
    with Session() as s:
        rows = s.query(OAuthState).filter(OAuthState.purpose == "signin").all()
        return rows[-1].state


def _mock_google(monkeypatch, sub="sub-1", email="dilshat@goodlabs.kz", verified=True):
    monkeypatch.setattr(
        oauth_mod, "exchange_code",
        lambda settings, code, code_verifier, redirect_uri=None: {"id_token": "idtok"})
    monkeypatch.setattr(
        oauth_mod, "verify_id_token",
        lambda settings, raw: {"sub": sub, "email": email, "email_verified": verified})


def test_signin_callback_sets_cookie_and_creates_user(api, monkeypatch):
    client, Session, settings = api
    state = _start_signin(client, Session)
    _mock_google(monkeypatch)

    r = client.get(f"/auth/google/callback?code=c&state={state}", follow_redirects=False)
    assert r.status_code == 200
    assert r.cookies.get("gads_session")
    assert "httponly" in r.headers["set-cookie"].lower()
    assert r.json()["user"]["email"] == "dilshat@goodlabs.kz"

    with Session() as s:
        user = s.query(User).one()
        assert user.google_sub == "sub-1"
        assert s.query(UserSession).one().user_id == user.id
        assert s.query(OAuthState).count() == 0   # consumed


def test_signin_twice_reuses_user_and_refreshes_email(api, monkeypatch):
    client, Session, settings = api

    state = _start_signin(client, Session)
    _mock_google(monkeypatch, sub="sub-1", email="old@goodlabs.kz")
    client.get(f"/auth/google/callback?code=c&state={state}", follow_redirects=False)

    state = _start_signin(client, Session)
    _mock_google(monkeypatch, sub="sub-1", email="new@goodlabs.kz")
    client.get(f"/auth/google/callback?code=c&state={state}", follow_redirects=False)

    with Session() as s:
        user = s.query(User).one()                # still one user
        assert user.email == "new@goodlabs.kz"
        assert s.query(UserSession).count() == 2  # one session per sign-in


def test_signin_callback_replay_rejected(api, monkeypatch):
    client, Session, settings = api
    state = _start_signin(client, Session)
    _mock_google(monkeypatch)
    client.get(f"/auth/google/callback?code=c&state={state}", follow_redirects=False)
    r2 = client.get(f"/auth/google/callback?code=c&state={state}", follow_redirects=False)
    assert r2.status_code == 400


def test_signin_callback_error_param_consumes_state(api):
    client, Session, settings = api
    state = _start_signin(client, Session)
    r = client.get(f"/auth/google/callback?error=access_denied&state={state}",
                   follow_redirects=False)
    assert r.status_code == 400
    assert "access_denied" in r.json()["detail"]
    with Session() as s:
        assert s.query(OAuthState).count() == 0


def test_signin_callback_rejects_missing_sub(api, monkeypatch):
    client, Session, settings = api
    # Seed a pre-existing user with NULL google_sub (e.g. a connect-flow user).
    with Session() as s:
        s.add(User(id="legacy", email="legacy@goodlabs.kz"))
        s.commit()
    state = _start_signin(client, Session)
    monkeypatch.setattr(
        oauth_mod, "exchange_code",
        lambda settings, code, code_verifier, redirect_uri=None: {"id_token": "idtok"})
    monkeypatch.setattr(
        oauth_mod, "verify_id_token",
        lambda settings, raw: {"email": "x@goodlabs.kz", "email_verified": True})  # no sub
    r = client.get(f"/auth/google/callback?code=c&state={state}", follow_redirects=False)
    assert r.status_code == 502
    # The legacy NULL-sub user must NOT have been hijacked / bound to a session.
    with Session() as s:
        assert s.query(UserSession).count() == 0
        assert s.get(User, "legacy").google_sub is None


def test_signin_rejects_email_outside_allowlist(make_api, monkeypatch):
    client, Session, settings = make_api(allowed_signins=["goodlabs.kz"])
    state = _start_signin(client, Session)
    _mock_google(monkeypatch, email="outsider@example.com")
    r = client.get(f"/auth/google/callback?code=c&state={state}", follow_redirects=False)
    assert r.status_code == 403
    with Session() as s:
        assert s.query(User).count() == 0
        assert s.query(UserSession).count() == 0


def test_signin_rejects_unverified_email(api, monkeypatch):
    client, Session, settings = api
    state = _start_signin(client, Session)
    _mock_google(monkeypatch, verified=False)
    r = client.get(f"/auth/google/callback?code=c&state={state}", follow_redirects=False)
    assert r.status_code == 403
    with Session() as s:
        assert s.query(User).count() == 0


def _mint_session(client, Session, settings, user_id="u1"):
    from app import sessions as sessions_mod
    with Session() as s:
        if s.get(User, user_id) is None:
            s.add(User(id=user_id, email="u1@example.com"))
            s.commit()
        token, _ = sessions_mod.create_session(s, user_id, settings.session_max_hours)
    client.cookies.set("gads_session", token)
    return token


def test_me_requires_signin(api):
    client, _, _ = api
    assert client.get("/me").status_code == 401


def test_me_rejects_bogus_cookie(api):
    client, _, _ = api
    client.cookies.set("gads_session", "not-a-real-token")
    assert client.get("/me").status_code == 401


def test_me_returns_signed_in_user(api):
    client, Session, settings = api
    _mint_session(client, Session, settings)
    r = client.get("/me")
    assert r.status_code == 200
    assert r.json() == {"id": "u1", "email": "u1@example.com"}


def test_logout_revokes_session(api):
    client, Session, settings = api
    _mint_session(client, Session, settings)
    r = client.post("/auth/logout")
    assert r.status_code == 200
    with Session() as s:
        assert s.query(UserSession).count() == 0
    client.cookies.clear()
    assert client.get("/me").status_code == 401

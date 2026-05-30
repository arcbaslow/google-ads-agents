from urllib.parse import urlparse, parse_qs

from app.oauth import build_authorization_url, make_pkce, new_state


def test_make_pkce_pair():
    verifier, challenge = make_pkce()
    assert 43 <= len(verifier) <= 128
    assert challenge and challenge != verifier


def test_new_state_is_random_and_urlsafe():
    a, b = new_state(), new_state()
    assert a != b
    assert len(a) >= 32


def test_authorization_url_has_required_params(settings):
    url = build_authorization_url(
        settings, state="STATE123", code_challenge="CHAL"
    )
    q = parse_qs(urlparse(url).query)
    assert q["client_id"] == [settings.google_oauth_client_id]
    assert q["redirect_uri"] == [settings.oauth_redirect_uri]
    assert q["response_type"] == ["code"]
    assert q["access_type"] == ["offline"]
    assert q["prompt"] == ["consent"]
    assert q["state"] == ["STATE123"]
    assert q["code_challenge"] == ["CHAL"]
    assert q["code_challenge_method"] == ["S256"]
    assert "https://www.googleapis.com/auth/adwords" in q["scope"][0]

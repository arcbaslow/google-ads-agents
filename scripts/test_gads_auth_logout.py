"""--logout revokes stored OAuth refresh tokens before clearing local files."""

from __future__ import annotations

import gads_auth


def _seed_oauth_profile(name: str = "acme", token: str = "rtok") -> None:
    gads_auth.add_profile(name, "DEV", "1")
    gads_auth.set_oauth_credentials(name, "cid", "secret", token)


def test_logout_revokes_oauth_profile_tokens(monkeypatch):
    _seed_oauth_profile()

    revoked = []
    monkeypatch.setattr(gads_auth, "revoke_refresh_token",
                        lambda token: revoked.append(token) or True)

    assert gads_auth.cmd_logout(None) == 0
    assert revoked == ["rtok"]
    assert gads_auth.load_credentials() == {}


def test_logout_clears_files_when_revocation_fails(monkeypatch):
    _seed_oauth_profile()

    def boom(token):
        raise OSError("network down")

    monkeypatch.setattr(gads_auth, "revoke_refresh_token", boom)

    assert gads_auth.cmd_logout(None) == 0
    assert gads_auth.load_credentials() == {}


def test_logout_skips_profiles_without_tokens(monkeypatch):
    gads_auth.add_profile("plain", "DEV", "1")

    revoked = []
    monkeypatch.setattr(gads_auth, "revoke_refresh_token",
                        lambda token: revoked.append(token) or True)

    assert gads_auth.cmd_logout(None) == 0
    assert revoked == []


def test_revoke_refresh_token_posts_to_google(monkeypatch):
    calls = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(url, data=None, timeout=None):
        calls["url"] = url
        calls["data"] = data
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert gads_auth.revoke_refresh_token("rtok") is True
    assert "revoke" in calls["url"]
    assert b"rtok" in calls["data"]

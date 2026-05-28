"""Auth profile management. No live API calls."""

from __future__ import annotations

import json

import pytest

import gads_auth


def test_add_first_profile_becomes_active():
    gads_auth.add_profile("acme", "DEV_TOKEN_1", "1234567890")
    assert gads_auth.active_profile_name() == "acme"
    assert gads_auth.get_developer_token() == "DEV_TOKEN_1"
    assert gads_auth.get_login_customer_id() == "1234567890"


def test_second_profile_does_not_steal_active():
    gads_auth.add_profile("acme", "DEV_TOKEN_1", "1111111111")
    gads_auth.add_profile("widgets", "DEV_TOKEN_2", "2222222222")
    assert gads_auth.active_profile_name() == "acme"


def test_use_profile_switches_active():
    gads_auth.add_profile("acme", "DEV_TOKEN_1", "1111111111")
    gads_auth.add_profile("widgets", "DEV_TOKEN_2", "2222222222")
    gads_auth.use_profile("widgets")
    assert gads_auth.active_profile_name() == "widgets"
    assert gads_auth.get_developer_token() == "DEV_TOKEN_2"
    assert gads_auth.get_login_customer_id() == "2222222222"


def test_use_missing_profile_raises():
    with pytest.raises(gads_auth.AuthRequiredError):
        gads_auth.use_profile("nope")


def test_remove_active_falls_back_to_remaining():
    gads_auth.add_profile("a", "T1", "1")
    gads_auth.add_profile("b", "T2", "2")
    gads_auth.remove_profile("a")
    # the only remaining profile takes over
    assert gads_auth.active_profile_name() == "b"


def test_remove_only_profile_clears_active():
    gads_auth.add_profile("a", "T1", "1")
    gads_auth.remove_profile("a")
    assert gads_auth.active_profile_name() is None
    with pytest.raises(gads_auth.AuthRequiredError):
        gads_auth.get_developer_token()


def test_env_overrides_profile_token(monkeypatch):
    gads_auth.add_profile("acme", "PROFILE_TOKEN", "1")
    monkeypatch.setenv("GOOGLE_ADS_DEVELOPER_TOKEN", "ENV_TOKEN")
    assert gads_auth.get_developer_token() == "ENV_TOKEN"


def test_env_overrides_login_customer_id(monkeypatch):
    gads_auth.add_profile("acme", "T", "1111111111")
    monkeypatch.setenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "999-888-7777")
    assert gads_auth.get_login_customer_id() == "9998887777"


def test_flat_credentials_file_migrates():
    """Old single-token files should turn into a default profile."""
    gads_auth.CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    gads_auth.CREDENTIALS_PATH.write_text(json.dumps({
        "developer_token": "LEGACY_TOKEN",
        "login_customer_id": "5555555555",
    }))
    # Triggers migration on read
    assert gads_auth.get_developer_token() == "LEGACY_TOKEN"
    assert gads_auth.active_profile_name() == "default"


def test_session_lifecycle():
    """Fresh session starts valid, can be expired by overwriting the marker."""
    from datetime import datetime, timedelta, timezone

    gads_auth.session_start()
    assert gads_auth.session_status()["valid"]

    # Pretend the session started 25h ago
    expired = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    gads_auth.SESSION_PATH.write_text(json.dumps({"started_at": expired}))
    assert gads_auth.session_status()["valid"] is False
    with pytest.raises(gads_auth.SessionExpiredError):
        gads_auth.enforce_session()


def test_list_profiles_shape():
    gads_auth.add_profile("acme", "T1", "1")
    gads_auth.add_profile("widgets", "T2", None)
    out = gads_auth.list_profiles()
    assert out["active"] == "acme"
    assert set(out["profiles"].keys()) == {"acme", "widgets"}
    assert out["profiles"]["widgets"]["login_customer_id"] is None
    assert out["profiles"]["acme"]["developer_token"] == "set"


def test_login_customer_id_strips_dashes():
    gads_auth.add_profile("acme", "T", "123-456-7890")
    assert gads_auth.get_login_customer_id() == "1234567890"


def test_migrated_profile_defaults_to_gcloud_method():
    gads_auth.add_profile("acme", "DEV", "1")
    assert gads_auth.active_profile().get("auth_method", "gcloud_adc") == "gcloud_adc"


def test_set_auth_method_persists():
    gads_auth.add_profile("acme", "DEV", "1")
    gads_auth.set_auth_method("acme", "oauth_client")
    assert gads_auth.active_profile()["auth_method"] == "oauth_client"


def test_set_oauth_credentials_sets_method_and_fields():
    gads_auth.add_profile("acme", "DEV", "1")
    gads_auth.set_oauth_credentials("acme", "cid", "sec", "rtok")
    prof = gads_auth.active_profile()
    assert prof["auth_method"] == "oauth_client"
    assert prof["client_id"] == "cid"
    assert prof["client_secret"] == "sec"
    assert prof["refresh_token"] == "rtok"


def test_set_oauth_credentials_creates_and_activates_profile():
    gads_auth.set_oauth_credentials("fresh", "cid", "sec", "rtok")
    assert gads_auth.active_profile_name() == "fresh"
    assert gads_auth.active_profile()["refresh_token"] == "rtok"


def test_get_credentials_uses_selected_backend(monkeypatch):
    """get_credentials dispatches to the backend chosen for the active profile."""
    import gads_authflow

    gads_auth.add_profile("acme", "DEV", "1")
    gads_auth.session_start()

    sentinel = object()

    class FakeBackend:
        def credentials(self):
            return sentinel

    monkeypatch.setattr(gads_authflow, "select_backend", lambda name, prof, **kw: FakeBackend())
    assert gads_auth.get_credentials() is sentinel


def test_get_credentials_expired_session_raises(monkeypatch):
    from datetime import datetime, timedelta, timezone

    gads_auth.add_profile("acme", "DEV", "1")
    expired = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    gads_auth.SESSION_PATH.write_text('{"started_at": "%s"}' % expired)
    with pytest.raises(gads_auth.SessionExpiredError):
        gads_auth.get_credentials()


def test_get_credentials_backend_failure_wraps_as_auth_required(monkeypatch):
    import gads_authflow

    gads_auth.add_profile("acme", "DEV", "1")
    gads_auth.session_start()

    class FailingBackend:
        def credentials(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(gads_authflow, "select_backend", lambda name, prof, **kw: FailingBackend())
    with pytest.raises(gads_auth.AuthRequiredError):
        gads_auth.get_credentials()

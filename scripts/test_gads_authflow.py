"""Auth backend selection and OAuth credential construction. No live API."""

from __future__ import annotations

import sys
import types

import gads_auth
import gads_authflow
import pytest


class _FakeStore:
    def __init__(self, rec):
        self._rec = rec

    def get(self, key):
        return self._rec

    def set(self, key, record):
        self._rec = record


def test_default_profile_selects_gcloud_backend():
    backend = gads_authflow.select_backend("acme", {})
    assert isinstance(backend, gads_authflow.GcloudAdcBackend)


def test_explicit_gcloud_method_selects_gcloud_backend():
    backend = gads_authflow.select_backend("acme", {"auth_method": "gcloud_adc"})
    assert isinstance(backend, gads_authflow.GcloudAdcBackend)


def test_oauth_method_selects_oauth_backend():
    store = _FakeStore({"client_id": "c", "client_secret": "s", "refresh_token": "r"})
    backend = gads_authflow.select_backend(
        "widgets", {"auth_method": "oauth_client"}, store=store
    )
    assert isinstance(backend, gads_authflow.OAuthClientBackend)


def test_oauth_method_without_token_raises():
    store = _FakeStore(None)
    with pytest.raises(gads_auth.AuthRequiredError):
        gads_authflow.select_backend(
            "widgets", {"auth_method": "oauth_client"}, store=store
        )


def test_oauth_backend_builds_and_refreshes_credentials(monkeypatch):
    """OAuthClientBackend constructs Credentials from the record and refreshes."""
    built = {}
    refreshed = {"called": False}

    class FakeCredentials:
        def __init__(self, **kwargs):
            built.update(kwargs)

        def refresh(self, request):
            refreshed["called"] = True

    oauth2 = types.ModuleType("google.oauth2")
    creds_mod = types.ModuleType("google.oauth2.credentials")
    creds_mod.Credentials = FakeCredentials
    transport = types.ModuleType("google.auth.transport")
    requests_mod = types.ModuleType("google.auth.transport.requests")
    requests_mod.Request = lambda: object()
    monkeypatch.setitem(sys.modules, "google.oauth2", oauth2)
    monkeypatch.setitem(sys.modules, "google.oauth2.credentials", creds_mod)
    monkeypatch.setitem(sys.modules, "google.auth.transport", transport)
    monkeypatch.setitem(sys.modules, "google.auth.transport.requests", requests_mod)

    backend = gads_authflow.OAuthClientBackend(
        {"client_id": "cid", "client_secret": "sec", "refresh_token": "rtok"}
    )
    backend.credentials()

    assert built["refresh_token"] == "rtok"
    assert built["client_id"] == "cid"
    assert built["client_secret"] == "sec"
    assert built["scopes"] == [gads_auth.ADWORDS]
    assert refreshed["called"] is True

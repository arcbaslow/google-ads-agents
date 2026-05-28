"""LocalFileTokenStore round-trips OAuth material inside a profile. No live API."""

from __future__ import annotations

import gads_auth
from gads_tokenstore import LocalFileTokenStore


def test_get_returns_none_when_no_profile():
    store = LocalFileTokenStore()
    assert store.get("missing") is None


def test_get_returns_none_without_refresh_token():
    gads_auth.add_profile("acme", "DEV", "1")
    store = LocalFileTokenStore()
    assert store.get("acme") is None


def test_set_then_get_round_trips():
    gads_auth.add_profile("acme", "DEV", "1")
    store = LocalFileTokenStore()
    store.set("acme", {
        "client_id": "cid",
        "client_secret": "secret",
        "refresh_token": "rtok",
    })
    rec = store.get("acme")
    assert rec == {"client_id": "cid", "client_secret": "secret", "refresh_token": "rtok"}


def test_set_preserves_existing_profile_fields():
    gads_auth.add_profile("acme", "DEV", "1234567890")
    store = LocalFileTokenStore()
    store.set("acme", {"client_id": "cid", "client_secret": "s", "refresh_token": "r"})
    assert gads_auth.get_developer_token() == "DEV"
    assert gads_auth.get_login_customer_id() == "1234567890"


def test_set_creates_profile_when_absent():
    store = LocalFileTokenStore()
    store.set("fresh", {"client_id": "c", "client_secret": "s", "refresh_token": "r"})
    assert store.get("fresh")["refresh_token"] == "r"

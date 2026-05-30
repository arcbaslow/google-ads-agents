from __future__ import annotations

import sys
import types

import gads_provider


def test_default_is_file_provider():
    assert isinstance(gads_provider.get_active_provider(), gads_provider.FileCredentialProvider)


def test_bind_swaps_provider_and_resets():
    class Fake:
        def get_credentials(self): return "C"
        def get_developer_token(self): return "DEV"
        def get_login_customer_id(self): return "111"

    fake = Fake()
    with gads_provider.bind_provider(fake):
        assert gads_provider.get_active_provider() is fake
    assert isinstance(gads_provider.get_active_provider(), gads_provider.FileCredentialProvider)


def test_build_client_uses_active_provider(monkeypatch):
    # Inject a fake google-ads client module so build_client() imports it.
    captured = {}

    class FakeClient:
        @classmethod
        def load_from_dict(cls, cfg):
            captured.update(cfg)
            return "CLIENT"

    fake_mod = types.ModuleType("google.ads.googleads.client")
    fake_mod.GoogleAdsClient = FakeClient
    monkeypatch.setitem(sys.modules, "google.ads.googleads.client", fake_mod)

    class Fake:
        def get_credentials(self): return "CREDS"
        def get_developer_token(self): return "DEV"
        def get_login_customer_id(self): return "1234567890"

    import gads_client
    with gads_provider.bind_provider(Fake()):
        assert gads_client.build_client() == "CLIENT"

    assert captured["developer_token"] == "DEV"
    assert captured["credentials"] == "CREDS"
    assert captured["login_customer_id"] == "1234567890"
    assert captured["use_proto_plus"] is True

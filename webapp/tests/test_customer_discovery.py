from unittest.mock import Mock

import gads_authflow
from app.routes.auth_routes import list_accessible_customers
from google.ads.googleads.client import GoogleAdsClient
from google.auth.credentials import AnonymousCredentials


def test_discovery_accepts_in_memory_credentials(settings, monkeypatch):
    credentials = AnonymousCredentials()
    refresh = Mock(return_value=credentials)
    monkeypatch.setattr(gads_authflow.OAuthClientBackend, "credentials", refresh)
    service = Mock()
    service.list_accessible_customers.return_value.resource_names = [
        "customers/123", "customers/456"]
    # Keep the real constructor: load_from_dict would reject this credential
    # shape. Mock only the service boundary; no transport is constructed.
    def get_service(client, name):
        assert client.version == "v25"
        assert name == "CustomerService"
        return service
    monkeypatch.setattr(GoogleAdsClient, "get_service", get_service)
    assert list_accessible_customers(settings, "mock-refresh") == ["123", "456"]
    refresh.assert_called_once_with()

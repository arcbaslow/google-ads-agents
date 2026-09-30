from unittest.mock import Mock

import gads_brands
import gads_client
import pytest
from google.ads.googleads.client import GoogleAdsClient
from google.auth.credentials import AnonymousCredentials


def test_suggest_reads_real_brand_response_fields(monkeypatch):
    types = GoogleAdsClient(credentials=AnonymousCredentials(), developer_token="test",
                           use_proto_plus=True)
    response = types.get_type("SuggestBrandsResponse")
    brand = types.get_type("BrandSuggestion")
    brand.id = "/m/acme"
    brand.name = "Acme"
    brand.urls.append("https://example.test")
    response.brands.append(brand)
    service = Mock()
    service.suggest_brands.return_value = response
    client = Mock(get_type=types.get_type)
    client.get_service.return_value = service
    monkeypatch.setattr(gads_client, "build_client", lambda: client)
    result = gads_brands.suggest("123", ["Acme"])
    assert result["suggestions"] == [{"query": "Acme", "id": "/m/acme",
        "name": "Acme", "urls": ["https://example.test"], "state": "UNSPECIFIED"}]
    request = service.suggest_brands.call_args.kwargs["request"]
    assert request.customer_id == "123"
    assert request.brand_prefix == "Acme"


@pytest.mark.parametrize("dry", [True, False])
def test_exclude_rejects_before_client_creation(monkeypatch, dry):
    build = Mock(side_effect=AssertionError("client must not be constructed"))
    monkeypatch.setattr(gads_client, "build_client", build)
    with pytest.raises(NotImplementedError, match="no exclusion was sent"):
        gads_brands.exclude("123", ["9"], ["/m/acme"], dry)
    build.assert_not_called()


@pytest.mark.parametrize("flag", ["--apply", "--validate-only"])
def test_exclude_cli_reports_unsupported_without_reading_input(monkeypatch, capsys, flag):
    import json

    monkeypatch.setattr("sys.argv", ["gads_brands", "--customer", "123", "exclude",
                        "--input", "nonexistent.json", flag, "--json"])
    assert gads_brands.main() == 2
    assert json.loads(capsys.readouterr().out)["status"] == "unsupported"

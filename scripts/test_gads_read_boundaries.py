"""Read contracts with real response messages and mocked transport only."""

import importlib
import io
import json
import urllib.error
from unittest.mock import Mock

import gads_client
import gads_geos
import gads_gtag
import gads_notify
import pytest
from google.ads.googleads.client import GoogleAdsClient
from google.api_core.exceptions import Forbidden, NotFound, ServiceUnavailable
from google.auth.credentials import AnonymousCredentials

READS = [
    ("competitors", "auction_insights", "rows", "metrics.search_impression_share"),
    ("display", "display_campaigns", "campaigns", "'DISPLAY'"),
    ("shopping", "shopping_campaigns", "campaigns", "campaign.shopping_setting.feed_label"),
    ("uac", "app_campaigns", "app_campaigns", "'MULTI_CHANNEL'"),
    ("youtube", "youtube_campaigns", "campaigns", "metrics.video_trueview_views"),
]


@pytest.fixture
def transport(monkeypatch):
    types = GoogleAdsClient(credentials=AnonymousCredentials(), version="v25", use_proto_plus=True)
    service = Mock()
    client = Mock(get_type=types.get_type)
    client.get_service.return_value = service
    monkeypatch.setattr(gads_client, "build_client", lambda: client)
    return service, types


@pytest.mark.parametrize("module,func,key,field", READS)
def test_read_rows_and_empty_results(transport, monkeypatch, module, func, key, field):
    service, types = transport
    adapter = importlib.import_module("gads_" + module)
    monkeypatch.setattr(adapter.gads_utils, "date_range", lambda days: ("2026-09-01", "2026-09-28"))
    batch = types.get_type("SearchGoogleAdsStreamResponse")
    row = types.get_type("GoogleAdsRow")
    row.campaign = {"id": 7, "name": "Example"}
    row.metrics = {"cost_micros": 1234567, "conversions": 1.5}
    batch.results.append(row)
    service.search_stream.return_value = [batch]
    result = getattr(adapter, func)("123")
    assert result[key][0]["campaign"]["id"] == "7"
    assert result[key][0]["metrics"]["cost_micros"] == "1234567"
    assert result[key][0]["metrics"]["conversions"] == 1.5
    query = service.search_stream.call_args.kwargs["query"]
    assert field in query and "2026-09-01" in query and "2026-09-28" in query
    assert service.search_stream.call_args.kwargs["customer_id"] == "123"
    service.search_stream.return_value = []
    assert getattr(adapter, func)("123")[key] == []


@pytest.mark.parametrize("module,func,key,field", READS)
@pytest.mark.parametrize("exc,code", [(Forbidden("private diagnostic"), "permission_denied"),
    (NotFound("private diagnostic"), "not_found"),
    (ServiceUnavailable("private diagnostic"), "temporarily_unavailable"),
    (AttributeError("private diagnostic"), "unexpected_error")])
def test_read_cli_redacts_errors(transport, monkeypatch, capsys, module, func, key, field, exc, code):
    service, _ = transport
    service.search_stream.side_effect = exc
    adapter = importlib.import_module("gads_" + module)
    monkeypatch.setattr("sys.argv", [module, "--customer", "123", "--json"])
    assert adapter.main() == 3
    output = capsys.readouterr()
    assert json.loads(output.out)["error_code"] == code
    assert "private diagnostic" not in output.out + output.err


def test_malformed_stream_is_failed_not_empty(transport, monkeypatch, capsys):
    import gads_display
    transport[0].search_stream.return_value = [object()]
    monkeypatch.setattr("sys.argv", ["display", "--customer", "123", "--json"])
    assert gads_display.main() == 3
    assert json.loads(capsys.readouterr().out)["status"] == "failed"


def test_geo_request_and_real_response(transport):
    service, types = transport
    response = types.get_type("SuggestGeoTargetConstantsResponse")
    response.geo_target_constant_suggestions.append({
        "search_term": "London", "locale": "en", "reach": 123,
        "geo_target_constant": {"id": 1006886, "name": "London", "country_code": "GB", "target_type": "City"},
    })
    service.suggest_geo_target_constants.return_value = response
    result = gads_geos.suggest("123", ["London"], "en", "GB")
    assert result["results"][0]["id"] == 1006886
    request = service.suggest_geo_target_constants.call_args.kwargs["request"]
    assert request.country_code == "GB" and list(request.location_names.names) == ["London"]
    response.geo_target_constant_suggestions.clear()
    assert gads_geos.suggest("123", ["London"])["results"] == []


@pytest.mark.parametrize("failure", [
    urllib.error.HTTPError("https://example.test/private-token", 403, "private-token", {}, io.BytesIO(b"private-token")),
    urllib.error.URLError("private-token"), TimeoutError("private-token"),
])
def test_network_errors_do_not_echo_urls_or_provider_bodies(monkeypatch, failure):
    monkeypatch.setattr("urllib.request.urlopen", Mock(side_effect=failure))
    monkeypatch.setattr(gads_notify, "load_telegram", lambda: {})
    results = [gads_gtag.scan_site("https://example.test"),
               gads_notify.send_message("test", token="private-token", chat_id="123"),
               gads_notify.discover_chat_id("private-token")]
    for result in results:
        assert result["status"] == "failed"
        assert "private-token" not in json.dumps(result)

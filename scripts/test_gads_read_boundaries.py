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


CHANNEL_ADAPTERS = [
    ("uac", "MULTI_CHANNEL", "app_campaigns", ["campaigns", "ads", "assets"]),
    ("display", "DISPLAY", "campaigns", ["campaigns", "ads"]),
    ("demandgen", "DEMAND_GEN", "campaigns", ["campaigns", "ads", "assets"]),
    ("youtube", "VIDEO", "campaigns", ["campaigns", "ads", "formats", "brand-safety"]),
]


def channel_row(types, campaign_status="ENABLED", ad_status="ENABLED", approval="DISAPPROVED"):
    row = types.get_type("GoogleAdsRow")
    row.campaign = {"id": 7, "name": "Campaign", "status": campaign_status,
                    "advertising_channel_sub_type": "APP_CAMPAIGN",
                    "bidding_strategy_type": "TARGET_CPA"}
    row.campaign_budget.amount_micros = 10000000
    row.ad_group = {"id": 8, "name": "Group"}
    row.ad_group_ad = {"resource_name": "customers/123/adGroupAds/8~9",
                       "ad": {"id": 9, "type_": "APP_AD"}, "status": ad_status,
                       "policy_summary": {"approval_status": approval, "review_status": "REVIEWED"}}
    row.ad_group_ad_asset_view = {
        "resource_name": "customers/123/adGroupAdAssetViews/8~9~10~HEADLINE",
        "ad_group_ad": "customers/123/adGroupAds/8~9", "asset": "customers/123/assets/10",
        "field_type": "HEADLINE", "performance_label": "LOW", "enabled": True,
        "policy_summary": {"approval_status": "APPROVED"},
    }
    row.metrics = {"impressions": 20, "cost_micros": 1234567, "conversions": 1.5,
                   "conversions_value": 12.5, "video_trueview_views": 3}
    row.segments.ad_sub_format_type = "INSTREAM_NON_SKIPPABLE_STANDARD"
    row.customer.video_brand_safety_suitability = "STANDARD_INVENTORY"
    return row


def set_channel_rows(service, types, rows):
    batch = types.get_type("SearchGoogleAdsStreamResponse")
    batch.results.extend(rows)
    service.search_stream.return_value = [batch]


@pytest.mark.parametrize("module,channel,key,kinds", CHANNEL_ADAPTERS)
def test_channel_campaign_fields_and_grouping(transport, module, channel, key, kinds):
    service, types = transport
    adapter = importlib.import_module("gads_" + module)
    rows = []
    for subtype in ["APP_CAMPAIGN", "APP_CAMPAIGN_FOR_ENGAGEMENT", "APP_CAMPAIGN_FOR_PRE_REGISTRATION"]:
        row = channel_row(types)
        row.campaign.advertising_channel_sub_type = subtype
        rows.append(row)
    set_channel_rows(service, types, rows)
    result = adapter.report("123-456-7890")
    first = result[key][0]
    assert first["campaign"]["status"] == "ENABLED"
    assert first["campaign"]["bidding_strategy_type"] == "TARGET_CPA"
    assert first["campaign_budget"]["amount_micros"] == "10000000"
    assert first["metrics"]["conversions_value"] == 12.5
    query = service.search_stream.call_args.kwargs["query"]
    for field in ["campaign.status", "campaign.advertising_channel_sub_type",
                  "campaign.bidding_strategy_type", "campaign_budget.amount_micros"]:
        assert field in query
    assert "campaign.status != 'REMOVED'" in query
    assert f"= '{channel}'" in query
    assert result["limitations"]
    if module == "uac":
        assert "metrics.conversions_value" in query
        assert list(result["by_sub_type"]) == [r.campaign.advertising_channel_sub_type.name for r in rows]
        assert all(len(group) == 1 for group in result["by_sub_type"].values())
        assert list(result["by_sub_type"].values()) == [[r] for r in result[key]]
    service.search_stream.return_value = []
    assert adapter.report("123")[key] == []


REPORT_CASES = [(module, channel, key, kind)
                for module, channel, key, kinds in CHANNEL_ADAPTERS for kind in kinds]


@pytest.mark.parametrize("module,channel,key,kind", REPORT_CASES)
def test_channel_cli_reports_real_rows_and_empty(transport, monkeypatch, capsys, module, channel, key, kind):
    service, types = transport
    adapter = importlib.import_module("gads_" + module)
    set_channel_rows(service, types, [channel_row(types)])
    monkeypatch.setattr("sys.argv", [module, "--customer", "123", "--report", kind, "--json"])
    assert adapter.main() == 0
    result = json.loads(capsys.readouterr().out)
    row = result[key if kind == "campaigns" else "rows"][0]
    query = service.search_stream.call_args.kwargs["query"]
    if kind == "ads":
        assert "FROM ad_group_ad" in query
        assert "ad_group_ad.status != 'REMOVED'" in query
        assert "segments.date" not in query and "metrics." not in query
        assert result["date_range"] is None
        assert row["ad_group_ad"]["ad"] == {"id": "9", "type": "APP_AD"}
        assert row["ad_group_ad"]["policy_summary"] == {
            "approval_status": "DISAPPROVED", "review_status": "REVIEWED"}
    elif kind == "assets":
        assert "FROM ad_group_ad_asset_view" in query
        link = row["ad_group_ad_asset_view"]
        assert link["ad_group_ad"].endswith("8~9") and link["asset"].endswith("/10")
        assert link["field_type"] == "HEADLINE" and link["performance_label"] == "LOW"
        assert link["enabled"] is True
        assert link["policy_summary"]["approval_status"] == "APPROVED"
    elif kind == "formats":
        assert "segments.ad_sub_format_type" in query
        assert row["segments"]["ad_sub_format_type"] == "INSTREAM_NON_SKIPPABLE_STANDARD"
        assert row["metrics"]["video_trueview_views"] == "3"
    elif kind == "brand-safety":
        assert "FROM customer" in query and "LIMIT 1" in query
        assert "segments.date" not in query and result["date_range"] is None
        assert row["customer"]["video_brand_safety_suitability"] == "STANDARD_INVENTORY"
    if kind != "brand-safety":
        assert f"= '{channel}'" in query and "campaign.status != 'REMOVED'" in query
    if kind not in {"ads", "brand-safety"}:
        assert result["date_range"]["start"] in query and result["date_range"]["end"] in query
    assert result["limitations"]
    service.search_stream.return_value = []
    assert adapter.main() == 0
    assert json.loads(capsys.readouterr().out)[key if kind == "campaigns" else "rows"] == []


@pytest.mark.parametrize("module,channel,key,kinds", CHANNEL_ADAPTERS)
@pytest.mark.parametrize("campaign_status,ad_status,approval,severity", [
    ("ENABLED", "ENABLED", "DISAPPROVED", "high"),
    ("PAUSED", "ENABLED", "DISAPPROVED", "high"),
    ("ENABLED", "ENABLED", "APPROVED_LIMITED", "medium"),
    ("PAUSED", "ENABLED", "APPROVED_LIMITED", "medium"),
    ("REMOVED", "ENABLED", "DISAPPROVED", None),
    ("UNKNOWN", "ENABLED", "DISAPPROVED", None),
    ("ENABLED", "PAUSED", "DISAPPROVED", None),
    ("ENABLED", "REMOVED", "APPROVED_LIMITED", None),
    ("ENABLED", "ENABLED", "APPROVED", None),
    ("ENABLED", "ENABLED", "UNKNOWN", None),
])
def test_channel_ad_findings(transport, module, channel, key, kinds,
                             campaign_status, ad_status, approval, severity):
    service, types = transport
    adapter = importlib.import_module("gads_" + module)
    row = channel_row(types, campaign_status, ad_status, approval)
    row.ad_group_ad_asset_view.enabled = False
    set_channel_rows(service, types, [row, row])
    result = adapter.audit("123")
    assert len(result["findings"]) == (1 if severity else 0)
    if severity:
        finding = result["findings"][0]
        assert finding["severity"] == severity
        assert finding["code"] == "ad_" + approval.lower()
        assert finding["entity"] == {"campaign_id": "7", "ad_group_id": "8", "ad_id": "9"}
        assert finding["message"]
    assert result[key] and result["summary"] and result["limitations"]
    if module == "demandgen":
        assert result["channel_controls"]
        assert "channel_controls.channel_config" in service.search_stream.call_args.kwargs["query"]
    service.search_stream.return_value = []
    assert adapter.audit("123")["findings"] == []


@pytest.mark.parametrize("enabled,label,count", [
    (True, "LOW", 1), (False, "LOW", 0), (True, "GOOD", 0), (True, "BEST", 0),
    (True, "LEARNING", 0), (True, "UNKNOWN", 0), (True, "PENDING", 0),
])
def test_app_asset_findings(transport, enabled, label, count):
    import gads_uac
    service, types = transport
    row = channel_row(types, approval="APPROVED")
    row.ad_group_ad_asset_view.enabled = enabled
    row.ad_group_ad_asset_view.performance_label = label
    set_channel_rows(service, types, [row, row])
    findings = gads_uac.audit("123")["findings"]
    assert len(findings) == count
    if count:
        assert findings[0]["severity"] == "low"
        assert findings[0]["code"] == "low_asset_performance"
        assert findings[0]["entity"] == {
            "campaign_id": "7", "ad_group_id": "8", "ad_group_ad": "customers/123/adGroupAds/8~9",
            "asset": "customers/123/assets/10", "field_type": "HEADLINE",
            "resource_name": "customers/123/adGroupAdAssetViews/8~9~10~HEADLINE",
        }


def test_asset_link_identity_preserves_distinct_ad_and_role(transport):
    import gads_findings
    import gads_uac
    service, types = transport
    rows = [channel_row(types, approval="APPROVED") for _ in range(3)]
    rows[1].ad_group_ad_asset_view.ad_group_ad = "customers/123/adGroupAds/8~11"
    rows[1].ad_group_ad_asset_view.resource_name = "customers/123/adGroupAdAssetViews/8~11~10~HEADLINE"
    rows[2].ad_group_ad_asset_view.field_type = "DESCRIPTION"
    rows[2].ad_group_ad_asset_view.resource_name = "customers/123/adGroupAdAssetViews/8~9~10~DESCRIPTION"
    set_channel_rows(service, types, rows)
    findings = gads_findings.collect({"agents": {"gads-uac": gads_uac.audit("123")}})
    assert len(findings) == len({gads_findings.identity(f) for f in findings}) == 3


@pytest.mark.parametrize("module,channel,key,kinds", CHANNEL_ADAPTERS)
def test_channel_audits_flow_through_driver_and_findings(transport, monkeypatch, module, channel, key, kinds):
    import gads_audit
    import gads_findings
    service, types = transport
    first = channel_row(types)
    second = channel_row(types, approval="APPROVED_LIMITED")
    second.ad_group_ad.ad.id = 11
    set_channel_rows(service, types, [first, second])
    name = "gads-" + module
    monkeypatch.setattr(gads_audit, "DEFAULT_AGENTS", [entry for entry in gads_audit.DEFAULT_AGENTS if entry[0] == name])
    result = gads_audit.run("123", 7, max_workers=1)
    findings = gads_findings.collect(result)
    assert len(findings) == (3 if module == "uac" else 2)
    assert len({gads_findings.identity(f) for f in findings}) == len(findings)
    assert all(f["agent"] == name and f["entity"]["campaign_id"] == "7" for f in findings)
    assert {f["entity"]["ad_id"] for f in findings if f["code"].startswith("ad_")} == {"9", "11"}
    assert result["agents"][name]["status"] == "ok"


@pytest.mark.parametrize("module,channel,key,kinds", CHANNEL_ADAPTERS)
def test_invalid_channel_reports_do_not_load_credentials(monkeypatch, module, channel, key, kinds):
    adapter = importlib.import_module("gads_" + module)
    build = Mock(side_effect=AssertionError("must validate before credentials"))
    monkeypatch.setattr(gads_client, "build_client", build)
    for kind in kinds:
        with pytest.raises(ValueError):
            adapter.report("123", 0, kind)
    with pytest.raises(ValueError):
        adapter.report("123", 28, "unsupported")
    with pytest.raises(ValueError):
        adapter.audit("123", -1)
    build.assert_not_called()


def test_changed_modules_import_from_this_worktree():
    from pathlib import Path
    for name in ["query", "uac", "display", "demandgen", "youtube", "audit"]:
        module = importlib.import_module("gads_" + name)
        assert Path(module.__file__).resolve().parent == Path(__file__).resolve().parent

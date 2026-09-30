"""RSA strength and PMax asset coverage rules — no API calls."""

from __future__ import annotations

import gads_assets


def _rsa_row(strength, headlines=10, descriptions=3, impressions=1000):
    return {
        "ad_group": {"id": "g1", "name": "Group A"},
        "ad_group_ad": {
            "ad_strength": strength,
            "status": "ENABLED",
            "ad": {
                "id": "ad1",
                "responsive_search_ad": {
                    "headlines": [{}] * headlines,
                    "descriptions": [{}] * descriptions,
                },
            },
        },
        "metrics": {"impressions": impressions, "clicks": 0, "conversions": 0},
    }


def test_rsa_poor_strength_high_severity(monkeypatch):
    monkeypatch.setattr(gads_assets.gads_client, "search_stream",
                        lambda c, q: [_rsa_row("POOR")])
    out = gads_assets.rsa_strength("123")
    assert out["findings"][0]["severity"] == "high"
    assert out["findings"][0]["code"] == "weak_rsa_strength"


def test_rsa_average_medium_severity(monkeypatch):
    monkeypatch.setattr(gads_assets.gads_client, "search_stream",
                        lambda c, q: [_rsa_row("AVERAGE")])
    out = gads_assets.rsa_strength("123")
    assert out["findings"][0]["severity"] == "medium"


def test_rsa_good_no_findings(monkeypatch):
    monkeypatch.setattr(gads_assets.gads_client, "search_stream",
                        lambda c, q: [_rsa_row("GOOD")])
    out = gads_assets.rsa_strength("123")
    assert out["findings"] == []


def test_rsa_weak_with_zero_impressions_skipped(monkeypatch):
    """No point flagging a paused / non-serving ad."""
    monkeypatch.setattr(gads_assets.gads_client, "search_stream",
                        lambda c, q: [_rsa_row("POOR", impressions=0)])
    out = gads_assets.rsa_strength("123")
    assert out["findings"] == []


def test_pmax_inventory_uses_real_fields_without_performance_conclusions(monkeypatch):
    from google.ads.googleads.client import GoogleAdsClient
    from google.auth.credentials import AnonymousCredentials

    types = GoogleAdsClient(credentials=AnonymousCredentials(), developer_token="test",
                           use_proto_plus=True, version="v25")
    rows = []
    for status in ["ENABLED", "PAUSED"]:
        row = types.get_type("GoogleAdsRow")
        row.asset_group.id = 1
        row.asset_group.name = "Group"
        row.asset_group_asset.asset = "customers/123/assets/7"
        row.asset_group_asset.field_type = types.enums.AssetFieldTypeEnum.HEADLINE
        row.asset_group_asset.status = getattr(types.enums.AssetLinkStatusEnum, status)
        rows.append(gads_assets.gads_client._row_to_dict(row))
    queries = []

    def search(customer, query):
        queries.append(query)
        return rows

    monkeypatch.setattr(gads_assets.gads_client, "search_stream", search)
    result = gads_assets.pmax_assets("123")
    assert "performance_label" not in queries[0]
    assert "PERFORMANCE_MAX" in queries[0]
    assert result["asset_groups"][0]["by_field_type"] == {
        "HEADLINE": {"total": 2, "by_status": {"ENABLED": 1, "PAUSED": 1}}}
    assert result["findings"] == []  # missing logos/video is not proof of a gap
    assert result["limitations"]


def test_pmax_empty_inventory_is_not_a_clean_bill_of_health(monkeypatch):
    monkeypatch.setattr(gads_assets.gads_client, "search_stream", lambda c, q: [])
    result = gads_assets.pmax_assets("123")
    assert result["asset_groups"] == []
    assert result["limitations"]

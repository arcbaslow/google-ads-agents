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


def _pmax_row(ag_id, ag_name, field_type, label="GOOD"):
    return {
        "asset_group": {"id": ag_id, "name": ag_name},
        "asset_group_asset": {
            "asset": f"asset/{field_type}",
            "field_type": field_type,
            "performance_label": label,
            "status": "ENABLED",
        },
    }


def test_pmax_full_coverage_no_findings(monkeypatch):
    rows = [_pmax_row("1", "AG", t) for t in gads_assets.REQUIRED_PMAX_TYPES]
    monkeypatch.setattr(gads_assets.gads_client, "search_stream", lambda c, q: rows)
    out = gads_assets.pmax_assets("123")
    assert out["findings"] == []


def test_pmax_missing_types_flagged(monkeypatch):
    rows = [_pmax_row("1", "AG", "HEADLINE")]
    monkeypatch.setattr(gads_assets.gads_client, "search_stream", lambda c, q: rows)
    out = gads_assets.pmax_assets("123")
    msgs = [f["message"] for f in out["findings"] if f["code"] == "pmax_asset_coverage_gap"]
    assert msgs and "VIDEO" in msgs[0]


def test_pmax_low_assets_flagged(monkeypatch):
    rows = [_pmax_row("1", "AG", t, "GOOD") for t in gads_assets.REQUIRED_PMAX_TYPES]
    rows.append(_pmax_row("1", "AG", "HEADLINE", "LOW"))
    monkeypatch.setattr(gads_assets.gads_client, "search_stream", lambda c, q: rows)
    out = gads_assets.pmax_assets("123")
    assert any(f["code"] == "pmax_low_assets_serving" for f in out["findings"])

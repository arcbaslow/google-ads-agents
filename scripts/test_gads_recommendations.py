"""Recommendations triage — no API calls."""

from __future__ import annotations

import json

import gads_recommendations


def _row(rtype, dismissed=False, base=None, potential=None, campaign=None):
    rec = {
        "type": rtype,
        "resource_name": f"customers/1/recommendations/{rtype}-1",
        "dismissed": dismissed,
        "impact": {
            "base_metrics": base or {},
            "potential_metrics": potential or {},
        },
    }
    if campaign:
        rec["campaign"] = campaign
    return {"recommendation": rec}


def _campaign_row(resource_name, name):
    return {"campaign": {"resource_name": resource_name, "name": name}}


def _dispatch(rec_rows, campaign_rows):
    """search_stream stub that answers the recommendation and campaign queries separately."""
    def _stream(cid, query):
        return campaign_rows if "FROM campaign" in query else rec_rows
    return _stream


def test_groups_by_type(monkeypatch):
    monkeypatch.setattr(gads_recommendations.gads_client, "search_stream",
                        lambda cid, q: [
                            _row("KEYWORD"),
                            _row("KEYWORD"),
                            _row("CALLOUT_EXTENSION"),
                        ])
    out = gads_recommendations.fetch("123")
    assert out["total"] == 3
    assert set(out["by_type"].keys()) == {"KEYWORD", "CALLOUT_EXTENSION"}
    assert len(out["by_type"]["KEYWORD"]) == 2


def test_dismissed_filtered_by_default(monkeypatch):
    monkeypatch.setattr(gads_recommendations.gads_client, "search_stream",
                        lambda cid, q: [
                            _row("KEYWORD"),
                            _row("KEYWORD", dismissed=True),
                        ])
    out = gads_recommendations.fetch("123")
    assert out["total"] == 1


def test_dismissed_included_when_requested(monkeypatch):
    monkeypatch.setattr(gads_recommendations.gads_client, "search_stream",
                        lambda cid, q: [
                            _row("KEYWORD"),
                            _row("KEYWORD", dismissed=True),
                        ])
    out = gads_recommendations.fetch("123", include_dismissed=True)
    assert out["total"] == 2


def test_impact_metrics_flattened(monkeypatch):
    monkeypatch.setattr(gads_recommendations.gads_client, "search_stream",
                        lambda cid, q: [_row(
                            "BUDGET",
                            base={"cost_micros": 10_000_000, "conversions": 2},
                            potential={"cost_micros": 20_000_000, "conversions": 5},
                        )])
    out = gads_recommendations.fetch("123")
    rec = out["by_type"]["BUDGET"][0]
    assert rec["base"]["cost"] == 10.0
    assert rec["potential"]["cost"] == 20.0
    assert rec["potential"]["conversions"] == 5


def test_query_selects_whole_impact_message():
    assert "recommendation.impact," in gads_recommendations.QUERY
    assert "recommendation.impact." not in gads_recommendations.QUERY


BRAND = "customers/1/campaigns/10"
GENERIC = "customers/1/campaigns/20"
CAMPAIGNS = [_campaign_row(BRAND, "Search - Brand"), _campaign_row(GENERIC, "Search - Generic")]


def test_brand_hold_collects_spend_expanding_recs_on_brand(monkeypatch):
    monkeypatch.setattr(gads_recommendations.gads_client, "search_stream", _dispatch([
        _row("CAMPAIGN_BUDGET", campaign=BRAND),
        _row("RAISE_TARGET_CPA", campaign=BRAND),
        _row("SITELINK_ASSET", campaign=BRAND),
        _row("CAMPAIGN_BUDGET", campaign=GENERIC),
    ], CAMPAIGNS))
    out = gads_recommendations.fetch("123")
    assert out["total"] == 4
    held = {(h["type"], h["campaign_name"]) for h in out["brand_hold"]}
    assert held == {("CAMPAIGN_BUDGET", "Search - Brand"), ("RAISE_TARGET_CPA", "Search - Brand")}
    assert all(h["brand"] and h["reason"] for h in out["brand_hold"])
    assert out["by_type"]["CAMPAIGN_BUDGET"][1]["brand"] is False
    assert out["by_type"]["SITELINK_ASSET"][0]["brand"] is True
    assert out["summary"][-1].startswith("brand_hold: 2")


def test_no_brand_hold_without_brand_campaigns(monkeypatch):
    monkeypatch.setattr(gads_recommendations.gads_client, "search_stream", _dispatch([
        _row("CAMPAIGN_BUDGET", campaign=GENERIC),
        _row("KEYWORD"),
    ], CAMPAIGNS))
    out = gads_recommendations.fetch("123")
    assert out["brand_hold"] == []
    assert not any(s.startswith("brand_hold") for s in out["summary"])
    assert out["by_type"]["KEYWORD"][0]["campaign_name"] is None


def test_dismissed_brand_recs_not_held_by_default(monkeypatch):
    monkeypatch.setattr(gads_recommendations.gads_client, "search_stream", _dispatch([
        _row("CAMPAIGN_BUDGET", campaign=BRAND, dismissed=True),
    ], CAMPAIGNS))
    assert gads_recommendations.fetch("123")["brand_hold"] == []


def test_brand_hold_by_search_term_share(monkeypatch, tmp_path):
    rules = tmp_path / "brand_rules.json"
    rules.write_text(json.dumps({
        "campaign_name_patterns": [],
        "brand_terms": {"123": ["acme"]},
        "brand_share_threshold": 0.7,
        "spend_expanding_recommendation_types": ["CAMPAIGN_BUDGET"],
    }))
    monkeypatch.setattr(gads_recommendations.gads_brandguard, "DEFAULT_RULES", rules)
    campaigns = [_campaign_row(BRAND, "Search - Acme Exact"), _campaign_row(GENERIC, "Search - Generic")]
    term_rows = [
        {"campaign": {"id": "10"}, "search_term_view": {"search_term": "acme"}, "metrics": {"clicks": 8}},
        {"campaign": {"id": "10"}, "search_term_view": {"search_term": "bank"}, "metrics": {"clicks": 2}},
        {"campaign": {"id": "20"}, "search_term_view": {"search_term": "acme"}, "metrics": {"clicks": 1}},
        {"campaign": {"id": "20"}, "search_term_view": {"search_term": "bank"}, "metrics": {"clicks": 9}},
    ]
    rec_rows = [_row("CAMPAIGN_BUDGET", campaign=BRAND), _row("CAMPAIGN_BUDGET", campaign=GENERIC)]

    def _stream(cid, query):
        if "search_term_view" in query:
            return term_rows
        return campaigns if "FROM campaign" in query else rec_rows

    monkeypatch.setattr(gads_recommendations.gads_client, "search_stream", _stream)
    out = gads_recommendations.fetch("123")
    assert [h["campaign_name"] for h in out["brand_hold"]] == ["Search - Acme Exact"]
    assert out["brand_hold"][0]["brand_reason"] == "search_terms"
    assert out["brand_hold"][0]["brand_share"] == 0.8
    generic = [r for r in out["by_type"]["CAMPAIGN_BUDGET"] if r["campaign"] == GENERIC][0]
    assert generic["brand"] is False and generic["brand_share"] == 0.1

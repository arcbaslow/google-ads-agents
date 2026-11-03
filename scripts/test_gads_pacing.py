"""Budget pacing — no API calls. We mock search_stream."""

from __future__ import annotations

import json
from datetime import date

import gads_pacing


def _row(campaign_id, name, budget_amount, date_str, cost):
    return {
        "campaign": {"id": campaign_id, "name": name, "status": "ENABLED"},
        "campaign_budget": {"amount_micros": budget_amount, "period": "DAILY"},
        "metrics": {"cost_micros": cost},
        "segments": {"date": date_str},
    }


def _mtd_rows(campaign_id, name, daily_budget_dollars, daily_cost_dollars):
    """Build rows covering 1..today for one campaign with constant daily spend."""
    today = date.today()
    rows = []
    for d in range(1, today.day + 1):
        rows.append(_row(
            campaign_id, name,
            budget_amount=int(daily_budget_dollars * 1_000_000),
            date_str=today.replace(day=d).isoformat(),
            cost=int(daily_cost_dollars * 1_000_000),
        ))
    return rows


def test_on_pace_no_findings(monkeypatch):
    rows = _mtd_rows("1", "On pace", daily_budget_dollars=50.0, daily_cost_dollars=50.0)
    monkeypatch.setattr(gads_pacing.gads_client, "search_stream", lambda c, q: rows)
    out = gads_pacing.analyze("123")
    assert out["findings"] == []


def test_overpacing_high(monkeypatch):
    rows = _mtd_rows("1", "Overpacer", daily_budget_dollars=50.0, daily_cost_dollars=80.0)
    monkeypatch.setattr(gads_pacing.gads_client, "search_stream", lambda c, q: rows)
    out = gads_pacing.analyze("123")
    findings = [f for f in out["findings"] if f["code"] == "overpacing"]
    assert findings
    assert findings[0]["severity"] in {"high", "medium"}


def test_underpacing(monkeypatch):
    rows = _mtd_rows("1", "Underpacer", daily_budget_dollars=100.0, daily_cost_dollars=20.0)
    monkeypatch.setattr(gads_pacing.gads_client, "search_stream", lambda c, q: rows)
    out = gads_pacing.analyze("123")
    findings = [f for f in out["findings"] if f["code"] == "underpacing"]
    assert findings


def test_brand_underpacing_gets_its_own_finding(monkeypatch):
    rows = _mtd_rows("1", "Search - Brand", daily_budget_dollars=100.0, daily_cost_dollars=20.0)
    monkeypatch.setattr(gads_pacing.gads_client, "search_stream", lambda c, q: rows)
    out = gads_pacing.analyze("123")
    assert out["campaigns"][0]["brand"] is True
    codes = [f["code"] for f in out["findings"]]
    assert codes == ["brand_underpacing"]
    assert out["findings"][0]["severity"] == "low"
    assert out["findings"][0]["brand"] is True
    assert "(1 brand)" in out["summary"]


def test_brand_overpacing_is_reported_normally(monkeypatch):
    rows = _mtd_rows("1", "Search - Brand", daily_budget_dollars=50.0, daily_cost_dollars=80.0)
    monkeypatch.setattr(gads_pacing.gads_client, "search_stream", lambda c, q: rows)
    out = gads_pacing.analyze("123")
    assert [f["code"] for f in out["findings"]] == ["overpacing"]


def test_brand_by_search_term_share(monkeypatch, tmp_path):
    rules = tmp_path / "brand_rules.json"
    rules.write_text(json.dumps({
        "campaign_name_patterns": [],
        "brand_terms": {"123": ["acme"]},
        "brand_share_threshold": 0.7,
        "spend_expanding_recommendation_types": [],
    }))
    monkeypatch.setattr(gads_pacing.gads_brandguard, "DEFAULT_RULES", rules)
    pacing_rows = _mtd_rows("1", "Search - Acme Exact", daily_budget_dollars=100.0, daily_cost_dollars=20.0)
    term_rows = [
        {"campaign": {"id": "1"}, "search_term_view": {"search_term": "acme bank"}, "metrics": {"clicks": 9}},
        {"campaign": {"id": "1"}, "search_term_view": {"search_term": "bank almaty"}, "metrics": {"clicks": 1}},
    ]
    monkeypatch.setattr(gads_pacing.gads_client, "search_stream",
                        lambda c, q: term_rows if "search_term_view" in q else pacing_rows)
    out = gads_pacing.analyze("123")
    campaign = out["campaigns"][0]
    assert campaign["brand"] is True
    assert campaign["brand_reason"] == "search_terms"
    assert campaign["brand_share"] == 0.9
    assert [f["code"] for f in out["findings"]] == ["brand_underpacing"]


def test_non_brand_campaigns_tagged_false(monkeypatch):
    rows = _mtd_rows("1", "Search - Generic", daily_budget_dollars=50.0, daily_cost_dollars=50.0)
    monkeypatch.setattr(gads_pacing.gads_client, "search_stream", lambda c, q: rows)
    out = gads_pacing.analyze("123")
    assert out["campaigns"][0]["brand"] is False
    assert out["campaigns"][0]["brand_reason"] is None


def test_zero_budget_campaigns_skipped(monkeypatch):
    rows = _mtd_rows("1", "No budget", daily_budget_dollars=0.0, daily_cost_dollars=0.0)
    monkeypatch.setattr(gads_pacing.gads_client, "search_stream", lambda c, q: rows)
    out = gads_pacing.analyze("123")
    assert out["campaigns"] == []

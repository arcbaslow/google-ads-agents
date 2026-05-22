"""Budget pacing — no API calls. We mock search_stream."""

from __future__ import annotations

from datetime import date, timedelta

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


def test_zero_budget_campaigns_skipped(monkeypatch):
    rows = _mtd_rows("1", "No budget", daily_budget_dollars=0.0, daily_cost_dollars=0.0)
    monkeypatch.setattr(gads_pacing.gads_client, "search_stream", lambda c, q: rows)
    out = gads_pacing.analyze("123")
    assert out["campaigns"] == []

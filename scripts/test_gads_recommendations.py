"""Recommendations triage — no API calls."""

from __future__ import annotations

import gads_recommendations


def _row(rtype, dismissed=False, base=None, potential=None):
    return {
        "recommendation": {
            "type": rtype,
            "resource_name": f"customers/1/recommendations/{rtype}-1",
            "dismissed": dismissed,
            "impact": {
                "base_metrics": base or {},
                "potential_metrics": potential or {},
            },
        },
    }


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

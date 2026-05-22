"""QS audit logic — no API calls."""

from __future__ import annotations

import gads_quality


def _row(qs, ctr_grade, ad_grade, lp_grade, impressions=500, cost_micros=10_000_000):
    return {
        "campaign": {"id": "1", "name": "Search Brand"},
        "ad_group": {"id": "2", "name": "Group A"},
        "ad_group_criterion": {
            "criterion_id": "9",
            "keyword": {"text": "buy widgets", "match_type": "EXACT"},
            "quality_info": {
                "quality_score": qs,
                "search_predicted_ctr": ctr_grade,
                "creative_quality_score": ad_grade,
                "post_click_quality_score": lp_grade,
            },
        },
        "metrics": {"impressions": impressions, "clicks": 10, "ctr": 0.02,
                    "cost_micros": cost_micros},
    }


def test_weakest_component_landing_page_ties_break_to_landing():
    weakest = gads_quality._weakest_component({
        "expected_ctr": "BELOW_AVERAGE",
        "ad_relevance": "BELOW_AVERAGE",
        "landing_page": "BELOW_AVERAGE",
    })
    assert weakest == "landing_page"


def test_weakest_component_picks_lowest_grade():
    weakest = gads_quality._weakest_component({
        "expected_ctr": "ABOVE_AVERAGE",
        "ad_relevance": "ABOVE_AVERAGE",
        "landing_page": "BELOW_AVERAGE",
    })
    assert weakest == "landing_page"


def test_weakest_component_handles_unspecified():
    weakest = gads_quality._weakest_component({
        "expected_ctr": "UNSPECIFIED",
        "ad_relevance": "AVERAGE",
        "landing_page": "ABOVE_AVERAGE",
    })
    assert weakest == "ad_relevance"


def test_finding_severity_high_at_qs_3(monkeypatch):
    monkeypatch.setattr(gads_quality.gads_client, "search_stream",
                        lambda c, q: [_row(3, "BELOW_AVERAGE", "AVERAGE", "AVERAGE")])
    out = gads_quality.audit("1")
    assert out["findings"][0]["severity"] == "high"
    assert out["findings"][0]["code"] == "low_qs_expected_ctr"


def test_finding_severity_medium_at_qs_6(monkeypatch):
    monkeypatch.setattr(gads_quality.gads_client, "search_stream",
                        lambda c, q: [_row(6, "AVERAGE", "AVERAGE", "BELOW_AVERAGE")])
    out = gads_quality.audit("1")
    assert out["findings"][0]["severity"] == "medium"
    assert "landing_page" in out["findings"][0]["code"]


def test_qs_7_emits_no_finding(monkeypatch):
    monkeypatch.setattr(gads_quality.gads_client, "search_stream",
                        lambda c, q: [_row(7, "AVERAGE", "AVERAGE", "AVERAGE")])
    out = gads_quality.audit("1")
    assert out["findings"] == []


def test_low_impressions_skipped(monkeypatch):
    monkeypatch.setattr(gads_quality.gads_client, "search_stream",
                        lambda c, q: [_row(3, "BELOW_AVERAGE", "AVERAGE", "AVERAGE",
                                            impressions=10)])
    out = gads_quality.audit("1", min_impressions=100)
    assert out["keywords"] == []
    assert out["findings"] == []


def test_weakest_component_counts_aggregated(monkeypatch):
    monkeypatch.setattr(gads_quality.gads_client, "search_stream", lambda c, q: [
        _row(4, "BELOW_AVERAGE", "AVERAGE", "AVERAGE"),
        _row(5, "AVERAGE", "BELOW_AVERAGE", "AVERAGE"),
        _row(3, "BELOW_AVERAGE", "AVERAGE", "AVERAGE"),
    ])
    out = gads_quality.audit("1")
    counts = out["weakest_component_counts"]
    assert counts["expected_ctr"] == 2
    assert counts["ad_relevance"] == 1
    assert counts["landing_page"] == 0


def test_keywords_sorted_by_qs_then_cost(monkeypatch):
    monkeypatch.setattr(gads_quality.gads_client, "search_stream", lambda c, q: [
        _row(6, "AVERAGE", "AVERAGE", "BELOW_AVERAGE", cost_micros=10_000_000),
        _row(3, "BELOW_AVERAGE", "AVERAGE", "AVERAGE", cost_micros=5_000_000),
        _row(3, "BELOW_AVERAGE", "AVERAGE", "AVERAGE", cost_micros=50_000_000),
    ])
    out = gads_quality.audit("1")
    # QS 3 keywords first; among them, highest cost first
    assert [k["quality_score"] for k in out["keywords"]] == [3, 3, 6]
    assert out["keywords"][0]["cost"] == 50.0

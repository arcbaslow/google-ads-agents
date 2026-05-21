"""Search-term mining logic — no API calls."""

from __future__ import annotations

import gads_search


def _row(term, clicks, cost_micros, conversions, campaign="1", ad_group="1"):
    return {
        "search_term_view": {"search_term": term},
        "campaign": {"id": campaign},
        "ad_group": {"id": ad_group},
        "metrics": {
            "clicks": clicks,
            "cost_micros": cost_micros,
            "conversions": conversions,
        },
    }


def test_negative_candidates_filters_converters(monkeypatch):
    monkeypatch.setattr(gads_search, "list_search_terms", lambda cid, days: {
        "date_range": {"start": "2025-01-01", "end": "2025-01-28"},
        "search_terms": [
            _row("converting term", clicks=10, cost_micros=20_000_000, conversions=1),
            _row("wasted term",     clicks=10, cost_micros=20_000_000, conversions=0),
        ],
    })
    out = gads_search.negative_candidates("123", days=28)
    terms = [c["search_term"] for c in out["candidates"]]
    assert terms == ["wasted term"]


def test_negative_candidates_skips_below_thresholds(monkeypatch):
    monkeypatch.setattr(gads_search, "list_search_terms", lambda cid, days: {
        "date_range": {"start": "2025-01-01", "end": "2025-01-28"},
        "search_terms": [
            _row("tiny term", clicks=2, cost_micros=1_000_000, conversions=0),
        ],
    })
    out = gads_search.negative_candidates("123", days=28, min_clicks=5, min_cost=10.0)
    assert out["candidates"] == []


def test_negative_candidates_emits_finding(monkeypatch):
    monkeypatch.setattr(gads_search, "list_search_terms", lambda cid, days: {
        "date_range": {"start": "2025-01-01", "end": "2025-01-28"},
        "search_terms": [
            _row("big waste", clicks=200, cost_micros=200_000_000, conversions=0),
        ],
    })
    out = gads_search.negative_candidates("123", days=28)
    assert out["findings"][0]["severity"] == "high"
    assert "wasted_spend_on_search_terms" == out["findings"][0]["code"]


def test_negative_candidates_sorted_by_cost_desc(monkeypatch):
    monkeypatch.setattr(gads_search, "list_search_terms", lambda cid, days: {
        "date_range": {"start": "2025-01-01", "end": "2025-01-28"},
        "search_terms": [
            _row("small loss",  clicks=10, cost_micros=12_000_000, conversions=0),
            _row("medium loss", clicks=10, cost_micros=50_000_000, conversions=0),
            _row("huge loss",   clicks=10, cost_micros=300_000_000, conversions=0),
        ],
    })
    out = gads_search.negative_candidates("123", days=28)
    assert [c["search_term"] for c in out["candidates"]] == [
        "huge loss", "medium loss", "small loss"
    ]

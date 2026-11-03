"""Brand classification rules - no API calls."""

from __future__ import annotations

import json

import gads_brandguard
import gads_client
import pytest


@pytest.fixture
def rules():
    return gads_brandguard.load_rules()


def _rules_file(tmp_path, **overrides):
    data = {
        "campaign_name_patterns": ["(?i)\\bbrand\\b"],
        "brand_terms": {},
        "brand_share_threshold": 0.7,
        "spend_expanding_recommendation_types": ["CAMPAIGN_BUDGET"],
    }
    data.update(overrides)
    path = tmp_path / "brand_rules.json"
    path.write_text(json.dumps(data))
    return path


def _term_row(campaign_id, term, clicks):
    return {
        "campaign": {"id": campaign_id},
        "search_term_view": {"search_term": term},
        "metrics": {"clicks": clicks},
    }


@pytest.mark.parametrize("name", [
    "Search - Brand",
    "BRAND | Exact",
    "Branded terms KZ",
    "Поиск Бренд",
    "brend search",
])
def test_default_patterns_match_brand_names(rules, name):
    assert gads_brandguard.is_brand_campaign(name, rules)


@pytest.mark.parametrize("name", [
    "Search - Generic",
    "PMax - All products",
    "Rebranding offer",
    "Brandon's bakery",
    "",
    None,
])
def test_default_patterns_skip_non_brand_names(rules, name):
    assert not gads_brandguard.is_brand_campaign(name, rules)


def test_rules_file_is_editable(tmp_path):
    rules = gads_brandguard.load_rules(_rules_file(
        tmp_path, campaign_name_patterns=["(?i)\\bacme\\b"]))
    assert gads_brandguard.is_brand_campaign("Search Acme exact", rules)
    assert not gads_brandguard.is_brand_campaign("Search Brand", rules)
    assert gads_brandguard.is_spend_expanding("CAMPAIGN_BUDGET", rules)
    assert not gads_brandguard.is_spend_expanding("SITELINK_ASSET", rules)


def test_default_rules_ship_without_brand_terms(rules):
    assert rules["brand_terms"] == {}
    assert rules["threshold"] == 0.7


def test_spend_expanding_types_are_real_enum_names(rules):
    from google.ads.googleads import v25

    enum = v25.enums.types.RecommendationTypeEnum.RecommendationType
    unknown = rules["spend_expanding"] - set(enum.__members__)
    assert unknown == set()


def test_asset_recommendations_are_not_spend_expanding(rules):
    for rtype in ("SITELINK_ASSET", "CALLOUT_ASSET", "RESPONSIVE_SEARCH_AD", "IMPROVE_GOOGLE_TAG_COVERAGE"):
        assert not gads_brandguard.is_spend_expanding(rtype, rules)


def test_no_brand_terms_sends_no_query(monkeypatch, tmp_path):
    rules = gads_brandguard.load_rules(_rules_file(tmp_path))
    monkeypatch.setattr(gads_client, "search_stream", lambda c, q: pytest.fail("unexpected query"))
    assert gads_brandguard.brand_shares("123", rules) == {}


def test_brand_terms_keyed_by_normalized_customer_id(tmp_path):
    rules = gads_brandguard.load_rules(_rules_file(
        tmp_path, brand_terms={"123-456-7890": ["Acme", "акме"]}))
    assert gads_brandguard.brand_terms_for("1234567890", rules) == ["acme", "акме"]
    assert gads_brandguard.brand_terms_for("123-456-7890", rules) == ["acme", "акме"]
    assert gads_brandguard.brand_terms_for("999", rules) == []


def test_brand_shares_from_search_terms(monkeypatch, tmp_path):
    rules = gads_brandguard.load_rules(_rules_file(tmp_path, brand_terms={"123": ["acme"]}))
    rows = [
        _term_row("10", "acme bank", 80),
        _term_row("10", "Acme Insurance", 10),
        _term_row("10", "car insurance", 10),
        _term_row("20", "car insurance almaty", 90),
        _term_row("20", "acme kasko", 10),
        _term_row("", "ignored", 5),
    ]
    monkeypatch.setattr(gads_client, "search_stream", lambda c, q: rows)
    shares = gads_brandguard.brand_shares("123", rules)
    assert shares["10"] == {"clicks": 100, "brand_clicks": 90, "share": 0.9}
    assert shares["20"] == {"clicks": 100, "brand_clicks": 10, "share": 0.1}
    assert set(shares) == {"10", "20"}


def test_brand_shares_are_cached(monkeypatch, tmp_path):
    rules = gads_brandguard.load_rules(_rules_file(tmp_path, brand_terms={"123": ["acme"]}))
    calls = []

    def _stream(c, q):
        calls.append(q)
        return [_term_row("10", "acme", 1)]

    monkeypatch.setattr(gads_client, "search_stream", _stream)
    first = gads_brandguard.brand_shares("123", rules)
    second = gads_brandguard.brand_shares("123", rules)
    assert first == second
    assert len(calls) == 1
    assert "FROM search_term_view" in calls[0]


def test_classify_by_name_or_share(tmp_path):
    rules = gads_brandguard.load_rules(_rules_file(tmp_path))
    shares = {"10": {"clicks": 100, "brand_clicks": 90, "share": 0.9},
              "20": {"clicks": 100, "brand_clicks": 10, "share": 0.1}}
    by_name = gads_brandguard.classify("Search - Brand", "20", shares, rules)
    assert by_name == {"brand": True, "brand_share": 0.1, "brand_reason": "name"}
    by_share = gads_brandguard.classify("Search - Acme Exact", "10", shares, rules)
    assert by_share == {"brand": True, "brand_share": 0.9, "brand_reason": "search_terms"}
    generic = gads_brandguard.classify("Search - Generic", "20", shares, rules)
    assert generic == {"brand": False, "brand_share": 0.1, "brand_reason": None}
    unknown = gads_brandguard.classify("PMax", "30", shares, rules)
    assert unknown == {"brand": False, "brand_share": None, "brand_reason": None}


def test_classify_threshold_is_inclusive(tmp_path):
    rules = gads_brandguard.load_rules(_rules_file(tmp_path, brand_share_threshold=0.5))
    shares = {"10": {"clicks": 10, "brand_clicks": 5, "share": 0.5}}
    assert gads_brandguard.classify("x", "10", shares, rules)["brand"] is True

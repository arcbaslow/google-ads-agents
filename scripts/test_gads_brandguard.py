"""Brand classification rules - no API calls."""

from __future__ import annotations

import json

import gads_brandguard
import pytest


@pytest.fixture
def rules():
    return gads_brandguard.load_rules()


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
    path = tmp_path / "brand_rules.json"
    path.write_text(json.dumps({
        "campaign_name_patterns": ["(?i)\\bacme\\b"],
        "spend_expanding_recommendation_types": ["CAMPAIGN_BUDGET"],
    }))
    rules = gads_brandguard.load_rules(path)
    assert gads_brandguard.is_brand_campaign("Search Acme exact", rules)
    assert not gads_brandguard.is_brand_campaign("Search Brand", rules)
    assert gads_brandguard.is_spend_expanding("CAMPAIGN_BUDGET", rules)
    assert not gads_brandguard.is_spend_expanding("SITELINK_ASSET", rules)


def test_spend_expanding_types_are_real_enum_names(rules):
    from google.ads.googleads import v25

    enum = v25.enums.types.RecommendationTypeEnum.RecommendationType
    unknown = rules["spend_expanding"] - set(enum.__members__)
    assert unknown == set()


def test_asset_recommendations_are_not_spend_expanding(rules):
    for rtype in ("SITELINK_ASSET", "CALLOUT_ASSET", "RESPONSIVE_SEARCH_AD", "IMPROVE_GOOGLE_TAG_COVERAGE"):
        assert not gads_brandguard.is_spend_expanding(rtype, rules)

"""GAQL builders are plain strings — assert they have the fields each domain needs."""

from __future__ import annotations

import re

import gads_query


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def test_search_campaigns_has_impression_share_metrics():
    q = _norm(gads_query.search_campaigns("2025-01-01", "2025-01-28"))
    assert "campaign.advertising_channel_type = 'SEARCH'" in q
    assert "metrics.search_impression_share" in q
    assert "BETWEEN '2025-01-01' AND '2025-01-28'" in q


def test_search_terms_filters_low_impression_noise():
    q = _norm(gads_query.search_terms("2025-01-01", "2025-01-28"))
    assert "search_term_view.search_term" in q
    assert "metrics.impressions > 10" in q


def test_pmax_targets_asset_groups():
    q = _norm(gads_query.pmax_asset_groups("2025-01-01", "2025-01-28"))
    assert "FROM asset_group" in q


def test_app_campaigns_filter_is_multi_channel():
    q = _norm(gads_query.app_campaigns("2025-01-01", "2025-01-28"))
    # Google Ads exposes UAC under MULTI_CHANNEL
    assert "campaign.advertising_channel_type = 'MULTI_CHANNEL'" in q
    assert "campaign.app_campaign_setting.app_id" in q


def test_youtube_campaigns_include_video_quartiles():
    q = _norm(gads_query.youtube_campaigns("2025-01-01", "2025-01-28"))
    assert "campaign.advertising_channel_type = 'VIDEO'" in q
    for quartile in ("p25_rate", "p50_rate", "p75_rate", "p100_rate"):
        assert f"metrics.video_quartile_{quartile}" in q


def test_placements_view_includes_impression_floor():
    q = _norm(gads_query.placements("2025-01-01", "2025-01-28"))
    assert "FROM detail_placement_view" in q
    assert "metrics.impressions > 100" in q


def test_conversion_actions_query_excludes_removed():
    q = _norm(gads_query.conversion_actions())
    assert "FROM conversion_action" in q
    assert "conversion_action.status != 'REMOVED'" in q
    assert "primary_for_goal" in q


def test_auction_insights_query_carries_impression_share_breakdown():
    q = _norm(gads_query.auction_insights("2025-01-01", "2025-01-28"))
    assert "metrics.search_budget_lost_impression_share" in q
    assert "metrics.search_rank_lost_impression_share" in q

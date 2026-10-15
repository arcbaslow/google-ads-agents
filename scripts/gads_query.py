"""GAQL queries grouped by domain.

Kept as plain strings so they're easy to diff and copy into the API
playground when debugging. Each builder returns one query string.
"""

from __future__ import annotations


def search_campaigns(start: str, end: str) -> str:
    return f"""
        SELECT
          campaign.id,
          campaign.name,
          campaign.status,
          campaign.advertising_channel_type,
          campaign.advertising_channel_sub_type,
          campaign_budget.amount_micros,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value,
          metrics.ctr,
          metrics.average_cpc,
          metrics.search_impression_share,
          metrics.search_top_impression_share,
          metrics.search_absolute_top_impression_share
        FROM campaign
        WHERE campaign.advertising_channel_type = 'SEARCH'
          AND segments.date BETWEEN '{start}' AND '{end}'
    """


def search_terms(start: str, end: str) -> str:
    return f"""
        SELECT
          search_term_view.search_term,
          campaign.id,
          ad_group.id,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions
        FROM search_term_view
        WHERE segments.date BETWEEN '{start}' AND '{end}'
          AND metrics.impressions > 10
    """


def pmax_asset_groups(start: str, end: str) -> str:
    return f"""
        SELECT
          asset_group.id,
          asset_group.name,
          asset_group.status,
          campaign.id,
          campaign.name,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value
        FROM asset_group
        WHERE segments.date BETWEEN '{start}' AND '{end}'
    """


def app_campaigns(start: str, end: str) -> str:
    return f"""
        SELECT
          campaign.id,
          campaign.name,
          campaign_budget.amount_micros,
          campaign_budget.period,
          campaign_budget.total_amount_micros,
          campaign.bidding_strategy_type,
          campaign.advertising_channel_sub_type,
          campaign.status,
          campaign.app_campaign_setting.app_id,
          campaign.app_campaign_setting.app_store,
          campaign.app_campaign_setting.bidding_strategy_goal_type,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value,
          metrics.all_conversions
        FROM campaign
        WHERE campaign.advertising_channel_type = 'MULTI_CHANNEL'
          AND campaign.status != 'REMOVED'
          AND segments.date BETWEEN '{start}' AND '{end}'
    """


def display_campaigns(start: str, end: str) -> str:
    return f"""
        SELECT
          campaign.id,
          campaign.name,
          campaign_budget.amount_micros,
          campaign_budget.period,
          campaign_budget.total_amount_micros,
          campaign.bidding_strategy_type,
          campaign.advertising_channel_sub_type,
          campaign.status,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions,
          metrics.video_trueview_views
        FROM campaign
        WHERE campaign.advertising_channel_type = 'DISPLAY'
          AND campaign.status != 'REMOVED'
          AND segments.date BETWEEN '{start}' AND '{end}'
    """


def demand_gen_campaigns(start: str, end: str) -> str:
    return f"""
        SELECT
          campaign.id,
          campaign.name,
          campaign_budget.amount_micros,
          campaign_budget.period,
          campaign_budget.total_amount_micros,
          campaign.advertising_channel_sub_type,
          campaign.status,
          campaign.bidding_strategy_type,
          metrics.impressions,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value
        FROM campaign
        WHERE campaign.advertising_channel_type = 'DEMAND_GEN'
          AND campaign.status != 'REMOVED'
          AND segments.date BETWEEN '{start}' AND '{end}'
    """


def shopping_campaigns(start: str, end: str) -> str:
    return f"""
        SELECT
          campaign.id,
          campaign.name,
          campaign.shopping_setting.merchant_id,
          campaign.shopping_setting.feed_label,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value
        FROM campaign
        WHERE campaign.advertising_channel_type IN ('SHOPPING')
          AND segments.date BETWEEN '{start}' AND '{end}'
    """


def youtube_campaigns(start: str, end: str) -> str:
    return f"""
        SELECT
          campaign.id,
          campaign.name,
          campaign_budget.amount_micros,
          campaign_budget.period,
          campaign_budget.total_amount_micros,
          campaign.bidding_strategy_type,
          campaign.advertising_channel_sub_type,
          campaign.status,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.video_trueview_views,
          metrics.video_trueview_view_rate,
          metrics.video_quartile_p25_rate,
          metrics.video_quartile_p50_rate,
          metrics.video_quartile_p75_rate,
          metrics.video_quartile_p100_rate
        FROM campaign
        WHERE campaign.advertising_channel_type = 'VIDEO'
          AND campaign.status != 'REMOVED'
          AND segments.date BETWEEN '{start}' AND '{end}'
    """


def placements(start: str, end: str) -> str:
    return f"""
        SELECT
          campaign.id,
          campaign.name,
          ad_group.id,
          detail_placement_view.placement,
          detail_placement_view.display_name,
          detail_placement_view.target_url,
          detail_placement_view.placement_type,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions
        FROM detail_placement_view
        WHERE segments.date BETWEEN '{start}' AND '{end}'
          AND metrics.impressions > 100
    """


def conversion_actions() -> str:
    return """
        SELECT
          conversion_action.id,
          conversion_action.name,
          conversion_action.status,
          conversion_action.type,
          conversion_action.category,
          conversion_action.primary_for_goal,
          conversion_action.attribution_model_settings.attribution_model,
          conversion_action.counting_type,
          conversion_action.click_through_lookback_window_days,
          conversion_action.view_through_lookback_window_days
        FROM conversion_action
        WHERE conversion_action.status != 'REMOVED'
    """


def auction_insights(start: str, end: str) -> str:
    return f"""
        SELECT
          campaign.id,
          campaign.name,
          metrics.search_impression_share,
          metrics.search_top_impression_share,
          metrics.search_absolute_top_impression_share,
          metrics.search_budget_lost_impression_share,
          metrics.search_rank_lost_impression_share
        FROM campaign
        WHERE segments.date BETWEEN '{start}' AND '{end}'
    """


def channel_ads(channel_type: str) -> str:
    if channel_type not in {"DEMAND_GEN", "MULTI_CHANNEL", "DISPLAY", "VIDEO"}:
        raise ValueError("Unsupported ad channel")
    # No metrics or date segment: disapproved ads rarely serve, and metric
    # queries drop rows without activity in the range.
    return f"""
        SELECT campaign.id, campaign.name, campaign.status,
          ad_group.id, ad_group.name, ad_group_ad.resource_name,
          ad_group_ad.ad.id, ad_group_ad.ad.type, ad_group_ad.status,
          ad_group_ad.policy_summary.approval_status,
          ad_group_ad.policy_summary.review_status
        FROM ad_group_ad
        WHERE campaign.advertising_channel_type = '{channel_type}'
          AND campaign.status != 'REMOVED'
          AND ad_group_ad.status != 'REMOVED'
    """


def channel_assets(start: str, end: str, channel_type: str) -> str:
    if channel_type not in {"DEMAND_GEN", "MULTI_CHANNEL"}:
        raise ValueError("Unsupported asset channel")
    # The server rejects policy_summary.approval_status on this view; select the whole message.
    return f"""
        SELECT campaign.id, ad_group.id,
          ad_group_ad_asset_view.resource_name,
          ad_group_ad_asset_view.ad_group_ad, ad_group_ad_asset_view.asset,
          ad_group_ad_asset_view.field_type, ad_group_ad_asset_view.performance_label,
          ad_group_ad_asset_view.enabled,
          ad_group_ad_asset_view.policy_summary,
          metrics.impressions
        FROM ad_group_ad_asset_view
        WHERE campaign.advertising_channel_type = '{channel_type}'
          AND campaign.status != 'REMOVED'
          AND ad_group_ad.status != 'REMOVED'
          AND segments.date BETWEEN '{start}' AND '{end}'
    """


def youtube_formats(start: str, end: str) -> str:
    return f"""
        SELECT campaign.id, campaign.name, segments.ad_sub_format_type,
          metrics.impressions, metrics.cost_micros, metrics.video_trueview_views
        FROM campaign
        WHERE campaign.advertising_channel_type = 'VIDEO'
          AND campaign.status != 'REMOVED'
          AND segments.date BETWEEN '{start}' AND '{end}'
    """


def youtube_brand_safety() -> str:
    return """
        SELECT customer.video_brand_safety_suitability
        FROM customer
        LIMIT 1
    """

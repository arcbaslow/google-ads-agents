"""Performance Max read path."""

from __future__ import annotations

import argparse
import sys

import gads_client
import gads_errors
import gads_query
import gads_utils

CHANNELS_QUERY = """
    SELECT campaign.id, campaign.name, segments.ad_network_type,
      segments.ad_using_product_data, segments.ad_using_video,
      metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions
    FROM campaign
    WHERE campaign.advertising_channel_type = 'PERFORMANCE_MAX'
      AND segments.date BETWEEN '{start}' AND '{end}'
"""
PLACEMENTS_QUERY = """
    SELECT campaign.id, performance_max_placement_view.display_name,
      performance_max_placement_view.placement, performance_max_placement_view.placement_type,
      performance_max_placement_view.target_url, segments.ad_network_type, metrics.impressions
    FROM performance_max_placement_view
    WHERE campaign.advertising_channel_type = 'PERFORMANCE_MAX'
      AND segments.date BETWEEN '{start}' AND '{end}'
"""
ASSETS_QUERY = """
    SELECT campaign.id, asset_group.id, asset_group_asset.asset,
      asset_group_asset.field_type, asset_group_asset.status,
      metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions
    FROM asset_group_asset
    WHERE campaign.advertising_channel_type = 'PERFORMANCE_MAX'
      AND asset_group_asset.status != 'REMOVED'
      AND segments.date BETWEEN '{start}' AND '{end}'
"""
BRANDING_QUERY = """
    SELECT campaign.id, campaign_asset.asset, campaign_asset.field_type, campaign_asset.status
    FROM campaign_asset
    WHERE campaign.advertising_channel_type = 'PERFORMANCE_MAX'
      AND campaign_asset.field_type IN ('BUSINESS_NAME', 'LOGO', 'LANDSCAPE_LOGO')
      AND campaign_asset.status != 'REMOVED'
"""

TRACKING_QUERY = """
    SELECT campaign.id, asset_group.id, asset_group.name,
      asset_group.tracking_url_template, asset_group.url_custom_parameters,
      asset_group.final_url_suffix
    FROM asset_group
    WHERE campaign.advertising_channel_type = 'PERFORMANCE_MAX'
      AND asset_group.status != 'REMOVED'
"""


def report(customer_id: str, days: int = 28, kind: str = "channels") -> dict:
    queries = {"channels": CHANNELS_QUERY, "placements": PLACEMENTS_QUERY,
               "assets": ASSETS_QUERY, "branding": BRANDING_QUERY, "tracking": TRACKING_QUERY}
    if days < 1 or kind not in queries:
        raise ValueError("Choose a supported report and positive days")
    customer_id = gads_utils.normalize_customer_id(customer_id)
    start, end = gads_utils.date_range(days)
    rows = gads_client.search_stream(customer_id, queries[kind].format(start=start, end=end))
    return {
        "customer_id": customer_id, "report": kind, "rows": rows,
        "date_range": None if kind in {"branding", "tracking"} else {"start": start, "end": end},
        "limitations": [
            "Placement reporting exposes impressions; it is not placement spend or conversion attribution.",
            "Assets can serve together; never sum asset rows into campaign totals.",
            "Branding is current campaign-link inventory, not proof of serving or complete asset coverage.",
            "Tracking fields describe group configuration, not resolved URLs or successful measurement.",
        ],
    }

def asset_groups(customer_id: str, days: int = 28) -> dict:
    start, end = gads_utils.date_range(days)
    rows = gads_client.search_stream(customer_id, gads_query.pmax_asset_groups(start, end))
    return {
        "customer_id": customer_id,
        "date_range": {"start": start, "end": end},
        "asset_groups": rows,
    }


@gads_errors.cli
def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--customer", required=True)
    p.add_argument("--days", type=int, default=28)
    p.add_argument("--json", action="store_true")
    p.add_argument("--report", choices=["groups", "channels", "placements", "assets", "branding", "tracking"],
                   default="groups")
    args = p.parse_args()
    cid = gads_utils.normalize_customer_id(args.customer)
    data = asset_groups(cid, args.days) if args.report == "groups" else report(cid, args.days, args.report)
    gads_utils.emit(data, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())

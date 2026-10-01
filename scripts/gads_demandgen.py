"""Read Demand Gen campaign totals without surface-specific click metrics."""

from __future__ import annotations

import argparse
import sys

import gads_client
import gads_errors
import gads_query
import gads_utils

CONTROLS_QUERY = """
    SELECT campaign.id, ad_group.id, ad_group.name,
      ad_group.demand_gen_ad_group_settings.channel_controls.channel_config,
      ad_group.demand_gen_ad_group_settings.channel_controls.channel_strategy,
      ad_group.demand_gen_ad_group_settings.channel_controls.selected_channels.youtube_in_feed,
      ad_group.demand_gen_ad_group_settings.channel_controls.selected_channels.youtube_in_stream,
      ad_group.demand_gen_ad_group_settings.channel_controls.selected_channels.youtube_shorts,
      ad_group.demand_gen_ad_group_settings.channel_controls.selected_channels.discover,
      ad_group.demand_gen_ad_group_settings.channel_controls.selected_channels.display,
      ad_group.demand_gen_ad_group_settings.channel_controls.selected_channels.gmail,
      ad_group.demand_gen_ad_group_settings.channel_controls.selected_channels.maps
    FROM ad_group
    WHERE campaign.advertising_channel_type = 'DEMAND_GEN'
      AND campaign.status != 'REMOVED' AND ad_group.status != 'REMOVED'
"""


def channel_controls(customer_id: str) -> dict:
    customer_id = gads_utils.normalize_customer_id(customer_id)
    return {"customer_id": customer_id,
            "channel_controls": gads_client.search_stream(customer_id, CONTROLS_QUERY),
            "limitations": ["Current ad-group configuration, not historical delivery or surface spend.",
                            "Use channel_config to interpret strategy versus selected flags."]}

def demand_gen_campaigns(customer_id: str, days: int = 28) -> dict:
    if days < 1:
        raise ValueError("days must be positive")
    customer_id = gads_utils.normalize_customer_id(customer_id)
    start, end = gads_utils.date_range(days)
    rows = gads_client.search_stream(customer_id, gads_query.demand_gen_campaigns(start, end))
    return {
        "customer_id": customer_id,
        "date_range": {"start": start, "end": end},
        "campaigns": rows,
        "limitations": [
            "Campaign totals only; no channel, audience or asset breakdown.",
            "Clicks are omitted because Demand Gen click reporting requires a separate filter.",
            "Metric queries can omit campaigns with no activity; this is not a complete inventory.",
        ],
    }


@gads_errors.cli
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--customer", required=True)
    parser.add_argument("--days", type=int, default=28)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--channel-controls", action="store_true")
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be positive")
    data = (channel_controls(args.customer) if args.channel_controls
            else demand_gen_campaigns(args.customer, args.days))
    gads_utils.emit(data, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Read Demand Gen campaign totals without surface-specific click metrics."""

from __future__ import annotations

import argparse
import sys

import gads_client
import gads_errors
import gads_findings
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

LIMITATIONS = [
    "Metric queries can omit entities with no activity; rows are not a complete inventory.",
    "Policy and configuration fields describe current state, not historical state or proof of serving.",
    "Frequency and unique-user metrics are not read.",
    "Asset performance labels are relative within the ad; assets can serve together, so do not sum asset impressions.",
    "Clicks are omitted because Demand Gen click reporting requires a separate filter.",
    "Channel controls are current configuration, not historical delivery or surface spend.",
]


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
        "limitations": list(LIMITATIONS),
    }


def report(customer_id: str, days: int = 28, kind: str = "campaigns") -> dict:
    if days < 1 or kind not in ["campaigns", "ads", "assets"]:
        raise ValueError("Choose a supported report and positive days")
    if kind == "campaigns":
        return demand_gen_campaigns(customer_id, days)
    customer_id = gads_utils.normalize_customer_id(customer_id)
    start, end = gads_utils.date_range(days)
    if kind == "ads":
        query = gads_query.channel_ads("DEMAND_GEN")
    else:
        query = gads_query.channel_assets(start, end, "DEMAND_GEN")
    return {
        "customer_id": customer_id, "report": kind,
        "date_range": None if kind == "ads" else {"start": start, "end": end},
        "rows": gads_client.search_stream(customer_id, query),
        "limitations": list(LIMITATIONS),
    }


def audit(customer_id: str, days: int = 28) -> dict:
    data = demand_gen_campaigns(customer_id, days)
    data["ads"] = report(customer_id, days, "ads")["rows"]
    findings = gads_findings.ad_policy_findings(data["ads"])
    data["channel_controls"] = channel_controls(customer_id)["channel_controls"]
    data["findings"] = findings
    data["summary"] = f"{len(data['campaigns'])} campaigns, {len(findings)} findings."
    return data


@gads_errors.cli
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--customer", required=True)
    parser.add_argument("--days", type=int, default=28)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--report", choices=["campaigns", "ads", "assets"], default="campaigns")
    parser.add_argument("--channel-controls", action="store_true")
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be positive")
    data = (channel_controls(args.customer) if args.channel_controls
            else report(args.customer, args.days, args.report))
    gads_utils.emit(data, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())

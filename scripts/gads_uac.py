"""App campaign (UAC) read path."""

from __future__ import annotations

import argparse
import sys

import gads_client
import gads_errors
import gads_findings
import gads_query
import gads_utils

LIMITATIONS = [
    "Metric queries can omit entities with no activity; rows are not a complete inventory.",
    "Policy and configuration fields describe current state, not historical state or proof of serving.",
    "Frequency and unique-user metrics are not read.",
    "Asset performance labels are relative within the ad; assets can serve together, so do not sum asset impressions.",
    "Conversions are not necessarily installs; conversion goals differ by app campaign subtype.",
    "SKAdNetwork, Firebase links and Install Referrer health are not read.",
]


def app_campaigns(customer_id: str, days: int = 28) -> dict:
    if days < 1:
        raise ValueError("days must be positive")
    customer_id = gads_utils.normalize_customer_id(customer_id)
    start, end = gads_utils.date_range(days)
    rows = gads_client.search_stream(customer_id, gads_query.app_campaigns(start, end))
    by_sub_type = {name: [] for name in (
        "APP_CAMPAIGN", "APP_CAMPAIGN_FOR_ENGAGEMENT", "APP_CAMPAIGN_FOR_PRE_REGISTRATION",
    )}
    for row in rows:
        sub_type = row.get("campaign", {}).get("advertising_channel_sub_type", "UNSPECIFIED")
        by_sub_type.setdefault(sub_type, []).append(row)
    return {
        "customer_id": customer_id,
        "date_range": {"start": start, "end": end},
        "app_campaigns": rows,
        "by_sub_type": by_sub_type,
        "limitations": list(LIMITATIONS),
    }


def report(customer_id: str, days: int = 28, kind: str = "campaigns") -> dict:
    if days < 1 or kind not in ["campaigns", "ads", "assets"]:
        raise ValueError("Choose a supported report and positive days")
    if kind == "campaigns":
        return app_campaigns(customer_id, days)
    customer_id = gads_utils.normalize_customer_id(customer_id)
    start, end = gads_utils.date_range(days)
    if kind == "ads":
        query = gads_query.channel_ads("MULTI_CHANNEL")
    else:
        query = gads_query.channel_assets(start, end, "MULTI_CHANNEL")
    return {
        "customer_id": customer_id, "report": kind,
        "date_range": None if kind == "ads" else {"start": start, "end": end},
        "rows": gads_client.search_stream(customer_id, query),
        "limitations": list(LIMITATIONS),
    }


def audit(customer_id: str, days: int = 28) -> dict:
    data = app_campaigns(customer_id, days)
    data["ads"] = report(customer_id, days, "ads")["rows"]
    findings = gads_findings.ad_policy_findings(data["ads"])
    data["assets"] = report(customer_id, days, "assets")["rows"]
    findings.extend(_asset_findings(data["assets"]))
    data["findings"] = findings
    data["summary"] = f"{len(data['app_campaigns'])} campaigns, {len(findings)} findings."
    return data


def _asset_findings(rows: list[dict]) -> list[dict]:
    findings = []
    seen = set()
    for row in rows:
        link = row.get("ad_group_ad_asset_view", {})
        if link.get("enabled") is not True or link.get("performance_label") != "LOW":
            continue
        entity = {"campaign_id": row.get("campaign", {}).get("id"),
                  "ad_group_id": row.get("ad_group", {}).get("id"),
                  "ad_group_ad": link.get("ad_group_ad"),
                  "asset": link.get("asset"), "field_type": link.get("field_type")}
        identity = tuple(entity.values())
        if identity in seen:
            continue
        seen.add(identity)
        entity["resource_name"] = link.get("resource_name")
        findings.append({
            "severity": "low", "code": "low_asset_performance", "entity": entity,
            "message": f"Enabled asset link {link.get('asset')} has relative performance label LOW.",
        })
    return findings


@gads_errors.cli
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--customer", required=True)
    parser.add_argument("--days", type=int, default=28)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--report", choices=["campaigns", "ads", "assets"], default="campaigns")
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be positive")
    data = report(args.customer, args.days, args.report)
    gads_utils.emit(data, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())

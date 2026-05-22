"""Demographic and geographic performance breakdowns.

Four breakdowns, one shape each: a per-bucket performance row plus
findings for buckets that look like outliers vs the campaign average.
The outlier rule:

  - Compute campaign-wide CPA from the breakdown rows.
  - For each bucket, flag if CPA is at least 2x the campaign mean AND
    the bucket consumed at least 5% of total spend.
  - Severity scales with the multiplier.

Sub-commands: age, gender, device, location, all.
"""

from __future__ import annotations

import argparse
import sys

import gads_client
import gads_utils

AGE_QUERY = """
    SELECT
      campaign.id,
      campaign.name,
      ad_group_criterion.age_range.type,
      metrics.impressions,
      metrics.clicks,
      metrics.cost_micros,
      metrics.conversions,
      metrics.conversions_value
    FROM age_view
    WHERE segments.date BETWEEN '{start}' AND '{end}'
"""

GENDER_QUERY = """
    SELECT
      campaign.id,
      campaign.name,
      ad_group_criterion.gender.type,
      metrics.impressions,
      metrics.clicks,
      metrics.cost_micros,
      metrics.conversions,
      metrics.conversions_value
    FROM gender_view
    WHERE segments.date BETWEEN '{start}' AND '{end}'
"""

DEVICE_QUERY = """
    SELECT
      campaign.id,
      campaign.name,
      segments.device,
      metrics.impressions,
      metrics.clicks,
      metrics.cost_micros,
      metrics.conversions,
      metrics.conversions_value
    FROM campaign
    WHERE segments.date BETWEEN '{start}' AND '{end}'
      AND campaign.status = 'ENABLED'
"""

LOCATION_QUERY = """
    SELECT
      campaign.id,
      campaign.name,
      user_location_view.country_criterion_id,
      user_location_view.targeting_location,
      metrics.impressions,
      metrics.clicks,
      metrics.cost_micros,
      metrics.conversions,
      metrics.conversions_value
    FROM user_location_view
    WHERE segments.date BETWEEN '{start}' AND '{end}'
"""


def _breakdown(customer_id: str, days: int, query_template: str,
               bucket_picker, dimension: str) -> dict:
    start, end = gads_utils.date_range(days)
    rows = gads_client.search_stream(customer_id, query_template.format(start=start, end=end))

    by_bucket: dict[str, dict] = {}
    by_campaign_totals: dict[str, dict] = {}
    for row in rows:
        bucket = bucket_picker(row) or "UNKNOWN"
        campaign_id = row.get("campaign", {}).get("id") or "?"
        campaign_name = row.get("campaign", {}).get("name") or "?"
        m = row.get("metrics", {})
        cost = gads_utils.micros_to_currency(m.get("cost_micros"))
        conv = float(m.get("conversions", 0) or 0)
        value = float(m.get("conversions_value", 0) or 0)

        key = f"{campaign_id}::{bucket}"
        slot = by_bucket.setdefault(key, {
            "campaign_id": campaign_id,
            "campaign_name": campaign_name,
            "bucket": bucket,
            "impressions": 0,
            "clicks": 0,
            "cost": 0.0,
            "conversions": 0.0,
            "value": 0.0,
        })
        slot["impressions"] += int(m.get("impressions", 0) or 0)
        slot["clicks"] += int(m.get("clicks", 0) or 0)
        slot["cost"] += cost
        slot["conversions"] += conv
        slot["value"] += value

        tot = by_campaign_totals.setdefault(campaign_id, {"cost": 0.0, "conversions": 0.0})
        tot["cost"] += cost
        tot["conversions"] += conv

    items: list[dict] = []
    findings: list[dict] = []
    for entry in by_bucket.values():
        cpa = (entry["cost"] / entry["conversions"]) if entry["conversions"] else None
        roas = (entry["value"] / entry["cost"]) if entry["cost"] else None
        item = {**entry, "cpa": round(cpa, 2) if cpa is not None else None,
                "roas": round(roas, 2) if roas is not None else None}
        items.append(item)

        tot = by_campaign_totals.get(entry["campaign_id"], {})
        campaign_cpa = (tot["cost"] / tot["conversions"]) if tot.get("conversions") else None
        if (cpa is not None and campaign_cpa is not None
                and tot["cost"] > 0
                and entry["cost"] / tot["cost"] >= 0.05
                and cpa >= 2 * campaign_cpa):
            multiplier = cpa / campaign_cpa
            findings.append({
                "severity": "high" if multiplier >= 3 else "medium",
                "code": f"{dimension}_cpa_outlier",
                "message": (
                    f"{entry['bucket']} in {entry['campaign_name']!r} has CPA "
                    f"${cpa:.2f} vs campaign CPA ${campaign_cpa:.2f} "
                    f"({multiplier:.1f}x). Consider a negative bid adjustment."
                ),
            })

    items.sort(key=lambda x: (-x["cost"]))
    return {
        "customer_id": customer_id,
        "date_range": {"start": start, "end": end},
        "dimension": dimension,
        "buckets": items,
        "findings": findings,
        "summary": f"{len(items)} {dimension} buckets, {len(findings)} CPA outlier(s)",
    }


def by_age(customer_id: str, days: int = 28) -> dict:
    return _breakdown(customer_id, days, AGE_QUERY,
                      lambda r: r.get("ad_group_criterion", {}).get("age_range", {}).get("type"),
                      "age")


def by_gender(customer_id: str, days: int = 28) -> dict:
    return _breakdown(customer_id, days, GENDER_QUERY,
                      lambda r: r.get("ad_group_criterion", {}).get("gender", {}).get("type"),
                      "gender")


def by_device(customer_id: str, days: int = 28) -> dict:
    return _breakdown(customer_id, days, DEVICE_QUERY,
                      lambda r: r.get("segments", {}).get("device"),
                      "device")


def by_location(customer_id: str, days: int = 28) -> dict:
    return _breakdown(customer_id, days, LOCATION_QUERY,
                      lambda r: r.get("user_location_view", {}).get("country_criterion_id"),
                      "location")


def all_breakdowns(customer_id: str, days: int = 28) -> dict:
    return {
        "customer_id": customer_id,
        "age": by_age(customer_id, days),
        "gender": by_gender(customer_id, days),
        "device": by_device(customer_id, days),
        "location": by_location(customer_id, days),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--customer", required=True)
    p.add_argument("--days", type=int, default=28)
    p.add_argument("--json", action="store_true")
    sub = p.add_subparsers(dest="dimension", required=True)
    for name in ("age", "gender", "device", "location", "all"):
        sub.add_parser(name)
    args = p.parse_args()
    cid = gads_utils.normalize_customer_id(args.customer)

    fn = {
        "age": by_age, "gender": by_gender, "device": by_device,
        "location": by_location, "all": all_breakdowns,
    }[args.dimension]
    gads_utils.emit(fn(cid, args.days), args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())

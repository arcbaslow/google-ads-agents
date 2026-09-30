"""Ad-strength and asset performance.

Two reads in one script:

  - rsa: Responsive Search Ads. Reports ad_strength per ad
         (POOR, AVERAGE, GOOD, EXCELLENT) and the headline/description
         counts. Flags ads with POOR/AVERAGE strength.

  - pmax-assets: linked asset inventory by field type and link status.
    No performance labels or required-coverage conclusions.
"""

from __future__ import annotations

import argparse
import sys

import gads_client
import gads_utils

RSA_QUERY = """
    SELECT
      ad_group.id,
      ad_group.name,
      ad_group_ad.ad.id,
      ad_group_ad.ad.name,
      ad_group_ad.status,
      ad_group_ad.ad_strength,
      ad_group_ad.ad.responsive_search_ad.headlines,
      ad_group_ad.ad.responsive_search_ad.descriptions,
      metrics.impressions,
      metrics.clicks,
      metrics.conversions
    FROM ad_group_ad
    WHERE ad_group_ad.ad.type = 'RESPONSIVE_SEARCH_AD'
      AND ad_group_ad.status != 'REMOVED'
      AND segments.date BETWEEN '{start}' AND '{end}'
"""

PMAX_ASSET_QUERY = """
    SELECT
      asset_group.id,
      asset_group.name,
      asset_group_asset.asset,
      asset_group_asset.field_type,
      asset_group_asset.status
    FROM asset_group_asset
    WHERE asset_group_asset.status != 'REMOVED'
      AND campaign.advertising_channel_type = 'PERFORMANCE_MAX'
"""

WEAK_RSA_STRENGTHS = {"POOR", "AVERAGE"}


def rsa_strength(customer_id: str, days: int = 28) -> dict:
    start, end = gads_utils.date_range(days)
    rows = gads_client.search_stream(customer_id, RSA_QUERY.format(start=start, end=end))
    ads = []
    findings: list[dict] = []
    for row in rows:
        ad = row.get("ad_group_ad", {})
        strength = ad.get("ad_strength", "UNSPECIFIED")
        rsa = ad.get("ad", {}).get("responsive_search_ad", {}) or {}
        headlines = len(rsa.get("headlines") or [])
        descriptions = len(rsa.get("descriptions") or [])
        m = row.get("metrics", {})
        impressions = int(m.get("impressions", 0) or 0)
        item = {
            "ad_group_id": row.get("ad_group", {}).get("id"),
            "ad_group_name": row.get("ad_group", {}).get("name"),
            "ad_id": ad.get("ad", {}).get("id"),
            "strength": strength,
            "headlines": headlines,
            "descriptions": descriptions,
            "impressions": impressions,
            "clicks": int(m.get("clicks", 0) or 0),
            "conversions": float(m.get("conversions", 0) or 0),
        }
        ads.append(item)

        if strength in WEAK_RSA_STRENGTHS and impressions > 0:
            findings.append({
                "severity": "high" if strength == "POOR" else "medium",
                "code": "weak_rsa_strength",
                "message": (
                    f"Ad {item['ad_id']} in {item['ad_group_name']!r} is "
                    f"{strength} (headlines={headlines}, "
                    f"descriptions={descriptions})."
                ),
            })
    return {
        "customer_id": customer_id,
        "date_range": {"start": start, "end": end},
        "ads": ads,
        "findings": findings,
        "summary": f"{len(ads)} RSAs scanned, {len(findings)} weak",
    }


def pmax_assets(customer_id: str) -> dict:
    rows = gads_client.search_stream(customer_id, PMAX_ASSET_QUERY)

    by_group: dict[str, dict] = {}
    for row in rows:
        ag = row.get("asset_group", {})
        ga = row.get("asset_group_asset", {})
        ag_id = ag.get("id")
        if not ag_id:
            continue
        entry = by_group.setdefault(ag_id, {
            "asset_group_id": ag_id,
            "asset_group_name": ag.get("name"),
            "by_field_type": {},
        })
        ft = ga.get("field_type", "UNKNOWN")
        status = ga.get("status", "UNSPECIFIED")
        bucket = entry["by_field_type"].setdefault(ft, {"total": 0, "by_status": {}})
        bucket["total"] += 1
        bucket["by_status"][status] = bucket["by_status"].get(status, 0) + 1

    return {
        "customer_id": customer_id,
        "asset_groups": list(by_group.values()),
        "findings": [],
        "limitations": [
            "Inventory of non-removed group links only; groups without links are absent.",
            "No performance labels, campaign-level branding or required-coverage assessment.",
            "Link status does not establish whether an asset is serving.",
        ],
        "summary": f"{len(by_group)} PMax asset groups with linked assets",
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--customer", required=True)
    p.add_argument("--days", type=int, default=28)
    sub = p.add_subparsers(dest="action", required=True)
    sub.add_parser("rsa", help="Responsive Search Ad strength audit")
    sub.add_parser("pmax-assets", help="PMax linked asset inventory")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    cid = gads_utils.normalize_customer_id(args.customer)

    if args.action == "rsa":
        data = rsa_strength(cid, args.days)
    else:
        data = pmax_assets(cid)
    gads_utils.emit(data, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())

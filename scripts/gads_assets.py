"""Ad-strength and asset performance.

Two reads in one script:

  - rsa: Responsive Search Ads. Reports ad_strength per ad
         (POOR, AVERAGE, GOOD, EXCELLENT) and the headline/description
         counts. Flags ads with POOR/AVERAGE strength.

  - pmax-assets: Performance Max asset performance labels at the
                 asset-group / asset level
                 (UNSPECIFIED, BEST, GOOD, LOW, LEARNING). Flags
                 assets labelled LOW that are still serving and asset
                 groups missing creative coverage by type.
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
      asset_group_asset.performance_label,
      asset_group_asset.status
    FROM asset_group_asset
    WHERE asset_group_asset.status != 'REMOVED'
"""

WEAK_RSA_STRENGTHS = {"POOR", "AVERAGE"}
LOW_PMAX_LABELS = {"LOW"}
REQUIRED_PMAX_TYPES = {"HEADLINE", "LONG_HEADLINE", "DESCRIPTION", "MARKETING_IMAGE",
                       "LOGO", "VIDEO"}


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
    findings: list[dict] = []
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
            "low_assets": [],
        })
        ft = ga.get("field_type", "UNKNOWN")
        label = ga.get("performance_label", "UNSPECIFIED")
        bucket = entry["by_field_type"].setdefault(ft, {"total": 0, "by_label": {}})
        bucket["total"] += 1
        bucket["by_label"][label] = bucket["by_label"].get(label, 0) + 1
        if label in LOW_PMAX_LABELS:
            entry["low_assets"].append({"asset": ga.get("asset"), "field_type": ft})

    for entry in by_group.values():
        present = set(entry["by_field_type"].keys())
        missing = REQUIRED_PMAX_TYPES - present
        if missing:
            findings.append({
                "severity": "medium",
                "code": "pmax_asset_coverage_gap",
                "message": (
                    f"{entry['asset_group_name']!r} missing asset types: "
                    + ", ".join(sorted(missing))
                ),
            })
        if entry["low_assets"]:
            findings.append({
                "severity": "low",
                "code": "pmax_low_assets_serving",
                "message": (
                    f"{entry['asset_group_name']!r} has "
                    f"{len(entry['low_assets'])} assets labelled LOW. "
                    "Replace or pause them."
                ),
            })

    return {
        "customer_id": customer_id,
        "asset_groups": list(by_group.values()),
        "findings": findings,
        "summary": f"{len(by_group)} PMax asset groups scanned, {len(findings)} finding(s)",
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--customer", required=True)
    p.add_argument("--days", type=int, default=28)
    sub = p.add_subparsers(dest="action", required=True)
    sub.add_parser("rsa", help="Responsive Search Ad strength audit")
    sub.add_parser("pmax-assets", help="PMax asset coverage and labels")
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

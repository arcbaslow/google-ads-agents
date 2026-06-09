"""Pull Google Ads recommendations.

Google maintains a Recommendations API that surfaces actionable items
the platform itself flags: missing keywords, low-quality ads, broken
conversion tracking, unused budget headroom, and so on. This script
fetches them, normalizes the rows, and groups by type so the audit
report can quote them inline rather than re-deriving them from scratch.

We never auto-apply a recommendation. The user decides.
"""

from __future__ import annotations

import argparse
import sys

import gads_client
import gads_utils

QUERY = """
    SELECT
      recommendation.resource_name,
      recommendation.type,
      recommendation.impact.base_metrics.impressions,
      recommendation.impact.base_metrics.clicks,
      recommendation.impact.base_metrics.cost_micros,
      recommendation.impact.base_metrics.conversions,
      recommendation.impact.potential_metrics.impressions,
      recommendation.impact.potential_metrics.clicks,
      recommendation.impact.potential_metrics.cost_micros,
      recommendation.impact.potential_metrics.conversions,
      recommendation.dismissed,
      recommendation.campaign,
      recommendation.ad_group
    FROM recommendation
"""


def fetch(customer_id: str, include_dismissed: bool = False) -> dict:
    customer_id = gads_utils.normalize_customer_id(customer_id)
    rows = gads_client.search_stream(customer_id, QUERY)
    by_type: dict[str, list[dict]] = {}
    for row in rows:
        rec = row.get("recommendation", {})
        if rec.get("dismissed") and not include_dismissed:
            continue
        rtype = rec.get("type", "UNKNOWN")
        impact = rec.get("impact", {})
        by_type.setdefault(rtype, []).append({
            "resource_name": rec.get("resource_name"),
            "campaign": rec.get("campaign"),
            "ad_group": rec.get("ad_group"),
            "base": _flatten_metrics(impact.get("base_metrics", {})),
            "potential": _flatten_metrics(impact.get("potential_metrics", {})),
        })
    return {
        "customer_id": customer_id,
        "total": sum(len(v) for v in by_type.values()),
        "by_type": by_type,
        "summary": _summarize(by_type),
    }


def _flatten_metrics(m: dict) -> dict:
    return {
        "impressions": int(m.get("impressions", 0) or 0),
        "clicks": int(m.get("clicks", 0) or 0),
        "cost": gads_utils.micros_to_currency(m.get("cost_micros")),
        "conversions": float(m.get("conversions", 0) or 0),
    }


def _summarize(by_type: dict[str, list[dict]]) -> list[str]:
    out: list[str] = []
    for rtype, recs in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
        out.append(f"{rtype}: {len(recs)}")
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--customer", required=True)
    p.add_argument("--include-dismissed", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    data = fetch(args.customer, include_dismissed=args.include_dismissed)
    gads_utils.emit(data, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())

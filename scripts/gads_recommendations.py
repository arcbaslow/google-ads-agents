"""Pull Google Ads recommendations.

Google maintains a Recommendations API that surfaces actionable items
the platform itself flags: missing keywords, low-quality ads, broken
conversion tracking, unused budget headroom, and so on. This script
fetches them, normalizes the rows, and groups by type so the audit
report can quote them inline rather than re-deriving them from scratch.

We never auto-apply a recommendation. The user decides.

Recommendations that would put more spend behind a brand campaign (budget
raises, looser targets, reach expansion; see brand_rules.json) are listed
again under `brand_hold`. Google rates those by reported conversions, which
on brand are mostly non-incremental. Brand is decided by campaign name or
by brand share of search-term clicks; see gads_brandguard.
"""

from __future__ import annotations

import argparse
import sys

import gads_brandguard
import gads_client
import gads_errors
import gads_utils

# The server rejects recommendation.impact subfields (selectable in the v25
# descriptors); the whole message returns the same base and potential metrics.
QUERY = """
    SELECT
      recommendation.resource_name,
      recommendation.type,
      recommendation.impact,
      recommendation.dismissed,
      recommendation.campaign,
      recommendation.ad_group
    FROM recommendation
"""

CAMPAIGN_NAMES_QUERY = """
    SELECT
      campaign.resource_name,
      campaign.name
    FROM campaign
    WHERE campaign.status != 'REMOVED'
"""


def fetch(customer_id: str, include_dismissed: bool = False) -> dict:
    customer_id = gads_utils.normalize_customer_id(customer_id)
    rows = gads_client.search_stream(customer_id, QUERY)
    names = _campaign_names(customer_id)
    brand_rules = gads_brandguard.load_rules()
    brand_shares = gads_brandguard.brand_shares(customer_id, brand_rules)
    by_type: dict[str, list[dict]] = {}
    brand_hold: list[dict] = []
    for row in rows:
        rec = row.get("recommendation", {})
        if rec.get("dismissed") and not include_dismissed:
            continue
        rtype = rec.get("type", "UNKNOWN")
        impact = rec.get("impact", {})
        campaign = rec.get("campaign") or ""
        campaign_name = names.get(campaign)
        item = {
            "resource_name": rec.get("resource_name"),
            "campaign": rec.get("campaign"),
            "campaign_name": campaign_name,
            **gads_brandguard.classify(campaign_name, campaign.rsplit("/", 1)[-1], brand_shares, brand_rules),
            "ad_group": rec.get("ad_group"),
            "base": _flatten_metrics(impact.get("base_metrics", {})),
            "potential": _flatten_metrics(impact.get("potential_metrics", {})),
        }
        by_type.setdefault(rtype, []).append(item)
        if item["brand"] and gads_brandguard.is_spend_expanding(rtype, brand_rules):
            brand_hold.append({"type": rtype, **item, "reason": gads_brandguard.HOLD_REASON})
    summary = _summarize(by_type)
    if brand_hold:
        summary.append(f"brand_hold: {len(brand_hold)} (spend-expanding, on brand campaigns)")
    return {
        "customer_id": customer_id,
        "total": sum(len(v) for v in by_type.values()),
        "by_type": by_type,
        "brand_hold": brand_hold,
        "summary": summary,
    }


def _campaign_names(customer_id: str) -> dict[str, str]:
    names: dict[str, str] = {}
    for row in gads_client.search_stream(customer_id, CAMPAIGN_NAMES_QUERY):
        c = row.get("campaign", {})
        if c.get("resource_name"):
            names[c["resource_name"]] = c.get("name") or ""
    return names


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


@gads_errors.cli
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

"""Quality Score audit.

Pulls keyword-level Quality Score and its three component grades
(expected CTR, ad relevance, landing-page experience), groups keywords
by which component is dragging QS down, and emits severity-scaled
findings.

QS only updates while a keyword has impressions. We filter to enabled
keywords with serving history in the window, otherwise we'd surface
stale grades that the API will never refresh.
"""

from __future__ import annotations

import argparse
import sys

import gads_client
import gads_utils

QUERY = """
    SELECT
      campaign.id,
      campaign.name,
      ad_group.id,
      ad_group.name,
      ad_group_criterion.criterion_id,
      ad_group_criterion.keyword.text,
      ad_group_criterion.keyword.match_type,
      ad_group_criterion.quality_info.quality_score,
      ad_group_criterion.quality_info.creative_quality_score,
      ad_group_criterion.quality_info.post_click_quality_score,
      ad_group_criterion.quality_info.search_predicted_ctr,
      metrics.impressions,
      metrics.clicks,
      metrics.ctr,
      metrics.cost_micros
    FROM keyword_view
    WHERE ad_group_criterion.type = 'KEYWORD'
      AND ad_group_criterion.status = 'ENABLED'
      AND segments.date BETWEEN '{start}' AND '{end}'
"""

# Component grade -> friendly label
COMPONENT_FIELD = {
    "expected_ctr": "search_predicted_ctr",
    "ad_relevance": "creative_quality_score",
    "landing_page": "post_click_quality_score",
}

GRADES = {"BELOW_AVERAGE": 0, "AVERAGE": 1, "ABOVE_AVERAGE": 2}


def audit(customer_id: str, days: int = 28, min_impressions: int = 100) -> dict:
    start, end = gads_utils.date_range(days)
    rows = gads_client.search_stream(customer_id, QUERY.format(start=start, end=end))

    keywords: list[dict] = []
    findings: list[dict] = []
    weakest_counts: dict[str, int] = {k: 0 for k in COMPONENT_FIELD}

    for row in rows:
        crit = row.get("ad_group_criterion", {})
        qi = crit.get("quality_info", {}) or {}
        qs = qi.get("quality_score")
        impressions = int(row.get("metrics", {}).get("impressions", 0) or 0)
        if qs is None or impressions < min_impressions:
            continue

        components = {
            "expected_ctr": qi.get("search_predicted_ctr"),
            "ad_relevance": qi.get("creative_quality_score"),
            "landing_page": qi.get("post_click_quality_score"),
        }
        weakest = _weakest_component(components)
        if weakest:
            weakest_counts[weakest] += 1

        item = {
            "campaign_name": row.get("campaign", {}).get("name"),
            "ad_group_name": row.get("ad_group", {}).get("name"),
            "keyword": crit.get("keyword", {}).get("text"),
            "match_type": crit.get("keyword", {}).get("match_type"),
            "quality_score": qs,
            "weakest_component": weakest,
            "components": components,
            "impressions": impressions,
            "cost": gads_utils.micros_to_currency(row.get("metrics", {}).get("cost_micros")),
        }
        keywords.append(item)

        f = _finding(item)
        if f:
            findings.append(f)

    keywords.sort(key=lambda k: (k["quality_score"], -k["cost"]))
    return {
        "customer_id": customer_id,
        "date_range": {"start": start, "end": end},
        "keywords": keywords,
        "weakest_component_counts": weakest_counts,
        "findings": findings,
        "summary": (
            f"{len(keywords)} keywords scored, {len(findings)} below QS 7. "
            f"Most common deficient component: "
            f"{max(weakest_counts, key=weakest_counts.get) if any(weakest_counts.values()) else 'n/a'}."
        ),
    }


def _weakest_component(components: dict) -> str | None:
    """Return the component name with the lowest grade.

    Treats missing or 'UNSPECIFIED' as unknown. Ties broken by the
    canonical order: landing_page < ad_relevance < expected_ctr (the
    one most expensive to fix wins, surfacing more carefully).
    """
    order = ["landing_page", "ad_relevance", "expected_ctr"]
    scored = []
    for i, key in enumerate(order):
        grade = components.get(key)
        if grade in GRADES:
            # (grade, canonical_index, key) — ties break by canonical order, not alpha
            scored.append((GRADES[grade], i, key))
    if not scored:
        return None
    scored.sort()
    return scored[0][2]


def _finding(item: dict) -> dict | None:
    qs = item["quality_score"]
    if qs >= 7:
        return None
    severity = (
        "high"   if qs <= 4
        else "medium" if qs <= 6
        else "low"
    )
    weakest = item.get("weakest_component") or "unknown"
    return {
        "severity": severity,
        "code": f"low_qs_{weakest}",
        "message": (
            f"Keyword {item['keyword']!r} in {item['ad_group_name']!r} "
            f"has QS {qs}. Weakest component: {weakest}."
        ),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--customer", required=True)
    p.add_argument("--days", type=int, default=28)
    p.add_argument("--min-impressions", type=int, default=100,
                   help="Skip keywords below this volume (QS unreliable)")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    cid = gads_utils.normalize_customer_id(args.customer)
    gads_utils.emit(audit(cid, args.days, args.min_impressions), args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())

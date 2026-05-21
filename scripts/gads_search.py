"""Search campaign read paths plus search-term mining."""

from __future__ import annotations

import argparse
import sys

import gads_client
import gads_query
import gads_utils

# Default thresholds for the negative-candidate miner. Tunable per call.
NEGATIVE_DEFAULTS = {
    "min_clicks": 5,         # at least this many clicks
    "min_cost": 10.0,        # or this much spend
    "max_conversions": 0.0,  # but no conversions
}


def list_campaigns(customer_id: str, days: int = 28) -> dict:
    start, end = gads_utils.date_range(days)
    rows = gads_client.search_stream(customer_id, gads_query.search_campaigns(start, end))
    return {
        "customer_id": customer_id,
        "date_range": {"start": start, "end": end},
        "campaigns": rows,
    }


def list_search_terms(customer_id: str, days: int = 28) -> dict:
    start, end = gads_utils.date_range(days)
    rows = gads_client.search_stream(customer_id, gads_query.search_terms(start, end))
    return {
        "customer_id": customer_id,
        "date_range": {"start": start, "end": end},
        "search_terms": rows,
    }


def negative_candidates(
    customer_id: str,
    days: int = 28,
    min_clicks: int = NEGATIVE_DEFAULTS["min_clicks"],
    min_cost: float = NEGATIVE_DEFAULTS["min_cost"],
    max_conversions: float = NEGATIVE_DEFAULTS["max_conversions"],
) -> dict:
    """Surface search terms with non-trivial spend or clicks and no conversions.

    These are the easy first-pass negatives. The agent layer decides
    whether to actually add them — this is just the candidate list.
    """
    raw = list_search_terms(customer_id, days)
    candidates: list[dict] = []
    for row in raw["search_terms"]:
        metrics = row.get("metrics", {})
        clicks = int(metrics.get("clicks", 0) or 0)
        cost = gads_utils.micros_to_currency(metrics.get("cost_micros"))
        conversions = float(metrics.get("conversions", 0) or 0)

        if conversions > max_conversions:
            continue
        if clicks < min_clicks and cost < min_cost:
            continue

        candidates.append({
            "search_term": row.get("search_term_view", {}).get("search_term"),
            "campaign_id": row.get("campaign", {}).get("id"),
            "ad_group_id": row.get("ad_group", {}).get("id"),
            "clicks": clicks,
            "cost": cost,
            "conversions": conversions,
        })
    candidates.sort(key=lambda c: -c["cost"])
    return {
        "customer_id": customer_id,
        "date_range": raw["date_range"],
        "thresholds": {
            "min_clicks": min_clicks,
            "min_cost": min_cost,
            "max_conversions": max_conversions,
        },
        "candidates": candidates,
        "summary": (
            f"{len(candidates)} candidate negatives ({min_clicks}+ clicks or "
            f"${min_cost:.0f}+ spend with ≤{max_conversions} conv)"
        ),
        "findings": _findings(candidates),
    }


def _findings(candidates: list[dict]) -> list[dict]:
    if not candidates:
        return []
    total_wasted = sum(c["cost"] for c in candidates)
    sev = "high" if total_wasted >= 100 else "medium" if total_wasted >= 25 else "low"
    return [{
        "severity": sev,
        "code": "wasted_spend_on_search_terms",
        "message": (
            f"${total_wasted:.2f} spent on {len(candidates)} non-converting "
            f"search terms — review for negative keyword candidates."
        ),
    }]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--customer", required=True)
    p.add_argument("--days", type=int, default=28)
    p.add_argument("--search-terms", action="store_true",
                   help="Raw search-term-view rows")
    p.add_argument("--negative-candidates", action="store_true",
                   help="Filter search terms into negative candidates")
    p.add_argument("--min-clicks", type=int, default=NEGATIVE_DEFAULTS["min_clicks"])
    p.add_argument("--min-cost", type=float, default=NEGATIVE_DEFAULTS["min_cost"])
    p.add_argument("--max-conversions", type=float,
                   default=NEGATIVE_DEFAULTS["max_conversions"])
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    cid = gads_utils.normalize_customer_id(args.customer)
    if args.negative_candidates:
        data = negative_candidates(
            cid, args.days, args.min_clicks, args.min_cost, args.max_conversions
        )
    elif args.search_terms:
        data = list_search_terms(cid, args.days)
    else:
        data = list_campaigns(cid, args.days)
    gads_utils.emit(data, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())

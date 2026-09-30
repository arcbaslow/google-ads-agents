"""Read Demand Gen campaign totals without surface-specific click metrics."""

from __future__ import annotations

import argparse
import sys

import gads_client
import gads_query
import gads_utils


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--customer", required=True)
    parser.add_argument("--days", type=int, default=28)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be positive")
    gads_utils.emit(demand_gen_campaigns(args.customer, args.days), args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Search campaign read paths."""

from __future__ import annotations

import argparse
import sys

import gads_client
import gads_query
import gads_utils


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


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--customer", required=True)
    p.add_argument("--days", type=int, default=28)
    p.add_argument("--search-terms", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    cid = gads_utils.normalize_customer_id(args.customer)
    if args.search_terms:
        data = list_search_terms(cid, args.days)
    else:
        data = list_campaigns(cid, args.days)
    gads_utils.emit(data, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())

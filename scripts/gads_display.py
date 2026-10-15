"""Display campaign read path."""

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
    "Responsive Display asset links are not supported by ad_group_ad_asset_view in v25.",
    "Targeting, audiences and placement safety are not evaluated.",
]


def display_campaigns(customer_id: str, days: int = 28) -> dict:
    if days < 1:
        raise ValueError("days must be positive")
    customer_id = gads_utils.normalize_customer_id(customer_id)
    start, end = gads_utils.date_range(days)
    rows = gads_client.search_stream(customer_id, gads_query.display_campaigns(start, end))
    return {
        "customer_id": customer_id,
        "date_range": {"start": start, "end": end},
        "campaigns": rows,
        "limitations": list(LIMITATIONS),
    }


def report(customer_id: str, days: int = 28, kind: str = "campaigns") -> dict:
    if days < 1 or kind not in ["campaigns", "ads"]:
        raise ValueError("Choose a supported report and positive days")
    if kind == "campaigns":
        return display_campaigns(customer_id, days)
    customer_id = gads_utils.normalize_customer_id(customer_id)
    return {
        "customer_id": customer_id, "report": kind,
        "date_range": None,
        "rows": gads_client.search_stream(customer_id, gads_query.channel_ads("DISPLAY")),
        "limitations": list(LIMITATIONS),
    }


def audit(customer_id: str, days: int = 28) -> dict:
    data = display_campaigns(customer_id, days)
    data["ads"] = report(customer_id, days, "ads")["rows"]
    findings = gads_findings.ad_policy_findings(data["ads"])
    data["findings"] = findings
    data["summary"] = f"{len(data['campaigns'])} campaigns, {len(findings)} findings."
    return data


@gads_errors.cli
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--customer", required=True)
    parser.add_argument("--days", type=int, default=28)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--report", choices=["campaigns", "ads"], default="campaigns")
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be positive")
    data = report(args.customer, args.days, args.report)
    gads_utils.emit(data, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())

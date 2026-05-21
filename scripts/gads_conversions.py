"""Conversion action inventory and health checks."""

from __future__ import annotations

import argparse
import sys

import gads_client
import gads_query
import gads_utils


def list_conversion_actions(customer_id: str) -> dict:
    rows = gads_client.search_stream(customer_id, gads_query.conversion_actions())
    primary = [r for r in rows if r.get("conversion_action", {}).get("primary_for_goal")]
    return {
        "customer_id": customer_id,
        "conversion_actions": rows,
        "summary": {
            "total": len(rows),
            "primary_for_goal": len(primary),
        },
    }


def health(customer_id: str) -> dict:
    data = list_conversion_actions(customer_id)
    findings = []
    if data["summary"]["primary_for_goal"] == 0:
        findings.append({
            "severity": "critical",
            "code": "no_primary_conversion",
            "message": "No conversion action is marked primary-for-goal. Smart Bidding will have nothing to optimize.",
        })
    if data["summary"]["total"] == 0:
        findings.append({
            "severity": "critical",
            "code": "no_conversion_actions",
            "message": "No conversion actions defined.",
        })
    data["findings"] = findings
    return data


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--customer", required=True)
    p.add_argument("--health", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    cid = gads_utils.normalize_customer_id(args.customer)
    data = health(cid) if args.health else list_conversion_actions(cid)
    gads_utils.emit(data, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())

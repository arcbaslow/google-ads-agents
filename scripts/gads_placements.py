"""Placement audit for Display and YouTube.

Pulls every placement that served impressions in the lookback window, then
classifies each one against a rules file. The default rules cover scams,
bots, politics, religion, games, gambling, adult, and made-for-ads sites.
Output lists the placements proposed for exclusion grouped by category;
the caller can review and then run the write path to apply them.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import gads_client
import gads_query
import gads_utils

DEFAULT_RULES = Path(__file__).parent / "placements_rules.json"


def load_rules(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    out = []
    for r in data.get("rules", []):
        out.append({"category": r["category"], "re": re.compile(r["pattern"])})
    return out


def classify(text: str, rules: list[dict]) -> str | None:
    if not text:
        return None
    for r in rules:
        if r["re"].search(text):
            return r["category"]
    return None


def scan(customer_id: str, days: int = 28, rules_path: Path = DEFAULT_RULES) -> dict:
    start, end = gads_utils.date_range(days)
    rows = gads_client.search_stream(customer_id, gads_query.placements(start, end))
    rules = load_rules(rules_path)

    by_category: dict[str, list[dict]] = {}
    safe: list[dict] = []
    for row in rows:
        place = row.get("detail_placement_view", {})
        candidate = " ".join(filter(None, [
            place.get("placement"),
            place.get("display_name"),
            place.get("target_url"),
        ]))
        category = classify(candidate, rules)
        entry = {
            "placement": place.get("placement"),
            "display_name": place.get("display_name"),
            "target_url": place.get("target_url"),
            "type": place.get("placement_type"),
            "impressions": int(row.get("metrics", {}).get("impressions", 0) or 0),
            "clicks": int(row.get("metrics", {}).get("clicks", 0) or 0),
            "cost": gads_utils.micros_to_currency(row.get("metrics", {}).get("cost_micros")),
        }
        if category:
            entry["category"] = category
            by_category.setdefault(category, []).append(entry)
        else:
            safe.append(entry)

    return {
        "customer_id": customer_id,
        "date_range": {"start": start, "end": end},
        "rules_file": str(rules_path),
        "to_exclude": by_category,
        "total_flagged": sum(len(v) for v in by_category.values()),
        "total_safe": len(safe),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--customer", required=True)
    p.add_argument("--days", type=int, default=28)
    p.add_argument("--rules", default=str(DEFAULT_RULES))
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    cid = gads_utils.normalize_customer_id(args.customer)
    data = scan(cid, args.days, Path(args.rules))
    gads_utils.emit(data, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())

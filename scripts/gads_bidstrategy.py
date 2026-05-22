"""Per-campaign bid strategy fit.

Google's own guidance: Smart Bidding strategies (Target CPA, Target
ROAS) need conversion volume to learn. The rules of thumb most account
managers use:

  - <15 conv / 30 days     -> MANUAL_CPC or MAXIMIZE_CLICKS while
                              you build conversion volume
  -  15-30 conv / 30 days  -> MAXIMIZE_CONVERSIONS (no target yet)
  -  30-50 conv / 30 days  -> MAXIMIZE_CONVERSIONS (consider Target CPA)
  - 50+   conv / 30 days   -> TARGET_CPA
  - 50+   conv with values -> TARGET_ROAS

This script pulls 30-day conversion volume per campaign, compares it to
the current bid strategy, and flags mismatches with severity. It is a
recommendation engine, not a writer — switching bid strategy is a
human call.
"""

from __future__ import annotations

import argparse
import sys

import gads_client
import gads_utils

CONV_FLOOR_TARGET_CPA = 30
CONV_FLOOR_TARGET_ROAS = 50

QUERY = """
    SELECT
      campaign.id,
      campaign.name,
      campaign.status,
      campaign.bidding_strategy_type,
      campaign.advertising_channel_type,
      metrics.conversions,
      metrics.conversions_value,
      metrics.cost_micros
    FROM campaign
    WHERE campaign.status = 'ENABLED'
      AND segments.date BETWEEN '{start}' AND '{end}'
"""


def analyze(customer_id: str, days: int = 30) -> dict:
    start, end = gads_utils.date_range(days)
    rows = gads_client.search_stream(customer_id, QUERY.format(start=start, end=end))

    summarized: list[dict] = []
    findings: list[dict] = []
    for row in rows:
        c = row.get("campaign", {})
        m = row.get("metrics", {})
        conv = float(m.get("conversions", 0) or 0)
        conv_value = float(m.get("conversions_value", 0) or 0)
        strategy = c.get("bidding_strategy_type", "?")
        recommended = _recommend(conv, conv_value)
        item = {
            "campaign_id": c.get("id"),
            "campaign_name": c.get("name"),
            "channel": c.get("advertising_channel_type"),
            "current_strategy": strategy,
            "recommended": recommended,
            "conversions_30d": conv,
            "conversion_value_30d": conv_value,
            "cost_30d": gads_utils.micros_to_currency(m.get("cost_micros")),
        }
        summarized.append(item)

        finding = _finding(item)
        if finding:
            findings.append(finding)

    return {
        "customer_id": customer_id,
        "date_range": {"start": start, "end": end},
        "campaigns": summarized,
        "findings": findings,
        "summary": f"{len(summarized)} active campaigns, {len(findings)} bid-strategy mismatch(es)",
    }


def _recommend(conv: float, conv_value: float) -> str:
    if conv < 15:
        return "MANUAL_CPC"  # not enough volume for Smart Bidding
    if conv < CONV_FLOOR_TARGET_CPA:
        return "MAXIMIZE_CONVERSIONS"
    if conv >= CONV_FLOOR_TARGET_ROAS and conv_value > 0:
        return "TARGET_ROAS"
    if conv >= CONV_FLOOR_TARGET_CPA:
        return "TARGET_CPA"
    return "MAXIMIZE_CONVERSIONS"


def _finding(item: dict) -> dict | None:
    current = item["current_strategy"]
    rec = item["recommended"]
    if current == rec:
        return None
    if current in ("TARGET_CPA", "TARGET_ROAS") and item["conversions_30d"] < CONV_FLOOR_TARGET_CPA:
        return {
            "severity": "high",
            "code": "smart_bidding_undervolume",
            "campaign_id": item["campaign_id"],
            "message": (
                f"{item['campaign_name']!r} is on {current} with only "
                f"{item['conversions_30d']:.0f} conv/30d. Smart Bidding needs "
                f"≥{CONV_FLOOR_TARGET_CPA}/30d to learn — consider "
                f"{rec}."
            ),
        }
    if current == "MANUAL_CPC" and item["conversions_30d"] >= CONV_FLOOR_TARGET_CPA:
        return {
            "severity": "medium",
            "code": "manual_with_smart_bidding_volume",
            "campaign_id": item["campaign_id"],
            "message": (
                f"{item['campaign_name']!r} is on MANUAL_CPC with "
                f"{item['conversions_30d']:.0f} conv/30d — enough volume to "
                f"move to {rec}."
            ),
        }
    return {
        "severity": "low",
        "code": "bid_strategy_mismatch",
        "campaign_id": item["campaign_id"],
        "message": (
            f"{item['campaign_name']!r} is on {current}; recommended "
            f"{rec} based on {item['conversions_30d']:.0f} conv/30d."
        ),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--customer", required=True)
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    cid = gads_utils.normalize_customer_id(args.customer)
    gads_utils.emit(analyze(cid, args.days), args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Budget pacing.

For each enabled campaign:

  - Pull MTD spend from segments.date
  - Read campaign_budget.amount_micros
  - Project end-of-month spend assuming current daily run-rate holds
  - Flag campaigns that will exceed budget by more than 10% (overpace)
    or fall short by more than 10% (underpace)

Daily over/under-pacing is normal; MTD projections smooth that noise.
"""

from __future__ import annotations

import argparse
import calendar
import sys
from datetime import date

import gads_client
import gads_utils

QUERY = """
    SELECT
      campaign.id,
      campaign.name,
      campaign.status,
      campaign_budget.amount_micros,
      campaign_budget.period,
      metrics.cost_micros,
      segments.date
    FROM campaign
    WHERE campaign.status = 'ENABLED'
      AND segments.date BETWEEN '{start}' AND '{end}'
"""

OVER_THRESHOLD = 0.10
UNDER_THRESHOLD = -0.10


def analyze(customer_id: str) -> dict:
    today = date.today()
    start = today.replace(day=1).isoformat()
    end = today.isoformat()
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    days_elapsed = today.day  # includes today

    rows = gads_client.search_stream(customer_id, QUERY.format(start=start, end=end))

    by_campaign: dict[str, dict] = {}
    for row in rows:
        c = row.get("campaign", {})
        cid_ = c.get("id")
        if not cid_:
            continue
        b = row.get("campaign_budget", {})
        m = row.get("metrics", {})
        entry = by_campaign.setdefault(cid_, {
            "campaign_id": cid_,
            "campaign_name": c.get("name"),
            "daily_budget": gads_utils.micros_to_currency(b.get("amount_micros")),
            "period": b.get("period"),
            "mtd_spend": 0.0,
            "days_with_spend": 0,
        })
        cost = gads_utils.micros_to_currency(m.get("cost_micros"))
        entry["mtd_spend"] += cost
        if cost > 0:
            entry["days_with_spend"] += 1

    items: list[dict] = []
    findings: list[dict] = []
    for entry in by_campaign.values():
        daily_budget = entry["daily_budget"]
        if daily_budget <= 0:
            continue
        expected_mtd = daily_budget * days_elapsed
        projected_eom = entry["mtd_spend"] / max(days_elapsed, 1) * days_in_month
        target_eom = daily_budget * days_in_month
        delta_pct = (projected_eom - target_eom) / target_eom if target_eom else 0.0

        item = {
            **entry,
            "expected_mtd": round(expected_mtd, 2),
            "projected_eom": round(projected_eom, 2),
            "target_eom": round(target_eom, 2),
            "delta_pct": round(delta_pct, 3),
        }
        items.append(item)

        if delta_pct > OVER_THRESHOLD:
            findings.append({
                "severity": "high" if delta_pct > 0.25 else "medium",
                "code": "overpacing",
                "campaign_id": entry["campaign_id"],
                "message": (
                    f"{entry['campaign_name']!r} on pace to spend "
                    f"${projected_eom:,.0f} this month vs "
                    f"${target_eom:,.0f} target ({delta_pct*100:+.0f}%)."
                ),
            })
        elif delta_pct < UNDER_THRESHOLD:
            findings.append({
                "severity": "medium" if delta_pct < -0.25 else "low",
                "code": "underpacing",
                "campaign_id": entry["campaign_id"],
                "message": (
                    f"{entry['campaign_name']!r} on pace to underdeliver — "
                    f"${projected_eom:,.0f} vs ${target_eom:,.0f} "
                    f"({delta_pct*100:+.0f}%)."
                ),
            })

    items.sort(key=lambda x: -x["delta_pct"])
    return {
        "customer_id": customer_id,
        "as_of": end,
        "days_elapsed": days_elapsed,
        "days_in_month": days_in_month,
        "campaigns": items,
        "findings": findings,
        "summary": f"{len(items)} campaigns, {len(findings)} pacing issue(s)",
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--customer", required=True)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    cid = gads_utils.normalize_customer_id(args.customer)
    gads_utils.emit(analyze(cid), args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Detect day-level anomalies in campaign metrics.

Pull daily campaign metrics for the last N days, compute a trailing
mean and standard deviation per campaign per metric, and flag any day
whose z-score exceeds a threshold. Returns the list of anomalies so
the agent layer can decide whether to surface them.

This is intentionally simple — a 14-day baseline and a 2.0 z-score
default. Useful for "what happened on Tuesday" investigations and as
a daily monitor.
"""

from __future__ import annotations

import argparse
import statistics
import sys

import gads_client
import gads_utils

METRICS = ("cost_micros", "conversions", "clicks", "impressions")


def _query(start: str, end: str) -> str:
    return f"""
        SELECT
          campaign.id,
          campaign.name,
          segments.date,
          metrics.cost_micros,
          metrics.clicks,
          metrics.impressions,
          metrics.conversions
        FROM campaign
        WHERE segments.date BETWEEN '{start}' AND '{end}'
          AND campaign.status = 'ENABLED'
        ORDER BY campaign.id, segments.date
    """


def detect(customer_id: str, days: int = 30, z_threshold: float = 2.0,
           baseline_days: int = 14) -> dict:
    start, end = gads_utils.date_range(days)
    rows = gads_client.search_stream(customer_id, _query(start, end))

    by_campaign: dict[str, list[dict]] = {}
    for row in rows:
        cid = row.get("campaign", {}).get("id")
        if not cid:
            continue
        by_campaign.setdefault(cid, []).append(row)

    anomalies: list[dict] = []
    for cid, series in by_campaign.items():
        series.sort(key=lambda r: r.get("segments", {}).get("date", ""))
        name = series[0].get("campaign", {}).get("name", cid)
        anomalies.extend(_scan_campaign(name, cid, series, z_threshold, baseline_days))

    return {
        "customer_id": customer_id,
        "date_range": {"start": start, "end": end},
        "z_threshold": z_threshold,
        "baseline_days": baseline_days,
        "anomalies": anomalies,
        "summary": f"{len(anomalies)} day-level anomalies across {len(by_campaign)} campaigns",
    }


def _scan_campaign(name: str, cid: str, series: list[dict],
                   z_threshold: float, baseline_days: int) -> list[dict]:
    out: list[dict] = []
    # Build per-metric series in date order
    for metric in METRICS:
        values: list[float] = []
        for row in series:
            m = row.get("metrics", {}).get(metric)
            values.append(float(m or 0))
        for i, value in enumerate(values):
            if i < baseline_days:
                continue
            window = values[i - baseline_days:i]
            mean = statistics.fmean(window)
            stdev = statistics.pstdev(window) or 0.0
            if stdev == 0:
                continue
            z = (value - mean) / stdev
            if abs(z) < z_threshold:
                continue
            out.append({
                "campaign_id": cid,
                "campaign_name": name,
                "date": series[i].get("segments", {}).get("date"),
                "metric": metric,
                "value": value if metric != "cost_micros" else gads_utils.micros_to_currency(value),
                "baseline_mean": mean if metric != "cost_micros" else gads_utils.micros_to_currency(mean),
                "z_score": round(z, 2),
                "direction": "up" if z > 0 else "down",
            })
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--customer", required=True)
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--baseline-days", type=int, default=14)
    p.add_argument("--z", type=float, default=2.0)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    cid = gads_utils.normalize_customer_id(args.customer)
    gads_utils.emit(detect(cid, args.days, args.z, args.baseline_days), args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Anomaly z-score logic — no API calls."""

from __future__ import annotations

import gads_anomalies


def _series(campaign_id, campaign_name, values_by_metric):
    """Build daily rows for one campaign."""
    rows = []
    days = max(len(v) for v in values_by_metric.values())
    for i in range(days):
        m = {}
        for metric, vals in values_by_metric.items():
            m[metric] = vals[i] if i < len(vals) else 0
        rows.append({
            "campaign": {"id": campaign_id, "name": campaign_name},
            "segments": {"date": f"2025-01-{i+1:02d}"},
            "metrics": m,
        })
    return rows


def test_no_anomalies_in_stable_series(monkeypatch):
    rows = _series("1", "Stable", {
        "cost_micros":   [10_000_000] * 20,
        "clicks":        [10] * 20,
        "impressions":   [1000] * 20,
        "conversions":   [1.0] * 20,
    })
    monkeypatch.setattr(gads_anomalies.gads_client, "search_stream",
                        lambda cid, q: rows)
    out = gads_anomalies.detect("123", days=20, baseline_days=14, z_threshold=2.0)
    assert out["anomalies"] == []


def test_spike_is_caught(monkeypatch):
    rows = _series("1", "Spiky", {
        "cost_micros":   [10_000_000] * 14 + [100_000_000] * 6,
        "clicks":        [10] * 20,
        "impressions":   [1000] * 20,
        "conversions":   [1.0] * 20,
    })
    monkeypatch.setattr(gads_anomalies.gads_client, "search_stream",
                        lambda cid, q: rows)
    out = gads_anomalies.detect("123", days=20, baseline_days=14, z_threshold=2.0)
    cost_anoms = [a for a in out["anomalies"] if a["metric"] == "cost_micros"]
    assert len(cost_anoms) >= 1
    assert cost_anoms[0]["direction"] == "up"
    # values in dollars
    assert cost_anoms[0]["value"] == 100.0


def test_drop_is_caught(monkeypatch):
    rows = _series("1", "Dropper", {
        "cost_micros":   [10_000_000] * 14 + [100_000] * 6,
        "clicks":        [10] * 20,
        "impressions":   [1000] * 20,
        "conversions":   [1.0] * 20,
    })
    monkeypatch.setattr(gads_anomalies.gads_client, "search_stream",
                        lambda cid, q: rows)
    out = gads_anomalies.detect("123", days=20, baseline_days=14, z_threshold=2.0)
    cost_anoms = [a for a in out["anomalies"] if a["metric"] == "cost_micros"]
    assert any(a["direction"] == "down" for a in cost_anoms)


def test_zero_stdev_baseline_is_ignored(monkeypatch):
    """All-zeros baseline should not blow up with divide-by-zero."""
    rows = _series("1", "Quiet", {
        "cost_micros":   [0] * 20,
        "clicks":        [0] * 20,
        "impressions":   [0] * 20,
        "conversions":   [0.0] * 20,
    })
    monkeypatch.setattr(gads_anomalies.gads_client, "search_stream",
                        lambda cid, q: rows)
    out = gads_anomalies.detect("123", days=20, baseline_days=14, z_threshold=2.0)
    assert out["anomalies"] == []

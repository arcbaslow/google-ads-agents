"""Demographics outlier rules — no API calls."""

from __future__ import annotations

import gads_demographics


def _row(campaign_id, campaign_name, bucket_key, bucket_value,
        clicks=10, cost_micros=20_000_000, conversions=1.0):
    return {
        "campaign": {"id": campaign_id, "name": campaign_name},
        "ad_group_criterion": {bucket_key: {"type": bucket_value}} if bucket_key else {},
        "segments": {"device": bucket_value} if bucket_key is None else {},
        "metrics": {
            "impressions": 1000,
            "clicks": clicks,
            "cost_micros": cost_micros,
            "conversions": conversions,
            "conversions_value": 0,
        },
    }


def _device_row(campaign_id, name, device, cost_micros, conversions):
    return {
        "campaign": {"id": campaign_id, "name": name},
        "segments": {"device": device},
        "metrics": {
            "impressions": 1000, "clicks": 50,
            "cost_micros": cost_micros, "conversions": conversions,
            "conversions_value": 0,
        },
    }


def test_no_outliers_when_buckets_perform_similarly(monkeypatch):
    rows = [
        _device_row("1", "C", "MOBILE", 50_000_000, 5.0),
        _device_row("1", "C", "DESKTOP", 50_000_000, 5.0),
    ]
    monkeypatch.setattr(gads_demographics.gads_client, "search_stream", lambda c, q: rows)
    out = gads_demographics.by_device("123")
    assert out["findings"] == []


def test_outlier_flagged_when_cpa_above_2x(monkeypatch):
    rows = [
        # Desktop: $10 CPA (50/5)
        _device_row("1", "C", "DESKTOP", 50_000_000, 5.0),
        # Mobile: $50 CPA (50/1)
        # Campaign CPA = ($50+$50) / (5+1) = $16.67. Mobile is 3x of that.
        _device_row("1", "C", "MOBILE", 50_000_000, 1.0),
    ]
    monkeypatch.setattr(gads_demographics.gads_client, "search_stream", lambda c, q: rows)
    out = gads_demographics.by_device("123")
    codes = [f["code"] for f in out["findings"]]
    assert "device_cpa_outlier" in codes


def test_outlier_high_severity_at_3x(monkeypatch):
    rows = [
        # Desktop $100, $10 CPA, 10 conv
        _device_row("1", "C", "DESKTOP", 100_000_000, 10.0),
        # Mobile $100, $100 CPA, 1 conv
        # Campaign CPA = $200/11 = $18.18, mobile $100 = 5.5x  -> high
        _device_row("1", "C", "MOBILE", 100_000_000, 1.0),
    ]
    monkeypatch.setattr(gads_demographics.gads_client, "search_stream", lambda c, q: rows)
    out = gads_demographics.by_device("123")
    assert any(f["severity"] == "high" for f in out["findings"])


def test_outlier_skipped_when_spend_share_too_small(monkeypatch):
    rows = [
        _device_row("1", "C", "DESKTOP", 100_000_000, 10.0),  # 99% of spend, $10 CPA
        _device_row("1", "C", "MOBILE",     500_000,   0.01),  # tiny share, bad CPA
    ]
    monkeypatch.setattr(gads_demographics.gads_client, "search_stream", lambda c, q: rows)
    out = gads_demographics.by_device("123")
    assert out["findings"] == []


def test_zero_conversions_bucket_not_flagged(monkeypatch):
    """No conversions means no CPA — we can't compute the outlier ratio."""
    rows = [
        _device_row("1", "C", "DESKTOP", 50_000_000, 5.0),
        _device_row("1", "C", "MOBILE",  50_000_000, 0.0),
    ]
    monkeypatch.setattr(gads_demographics.gads_client, "search_stream", lambda c, q: rows)
    out = gads_demographics.by_device("123")
    assert out["findings"] == []


def test_all_combines_all_dimensions(monkeypatch):
    monkeypatch.setattr(gads_demographics.gads_client, "search_stream", lambda c, q: [])
    out = gads_demographics.all_breakdowns("123")
    assert set(out.keys()) == {"customer_id", "age", "gender", "device", "location"}

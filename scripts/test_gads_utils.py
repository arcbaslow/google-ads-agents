"""Shared helpers."""

from __future__ import annotations

from datetime import date, timedelta

import gads_utils


def test_date_range_is_yesterday_back_n_days():
    start, end = gads_utils.date_range(7)
    end_d = date.fromisoformat(end)
    start_d = date.fromisoformat(start)
    assert end_d == date.today() - timedelta(days=1)
    assert (end_d - start_d).days == 6  # 7-day window inclusive


def test_micros_to_currency():
    assert gads_utils.micros_to_currency(1_000_000) == 1.0
    assert gads_utils.micros_to_currency(1_500_000) == 1.5
    assert gads_utils.micros_to_currency(None) == 0.0
    assert gads_utils.micros_to_currency("2500000") == 2.5


def test_normalize_customer_id():
    assert gads_utils.normalize_customer_id("123-456-7890") == "1234567890"
    assert gads_utils.normalize_customer_id("  1234567890  ") == "1234567890"


def test_cache_round_trip(monkeypatch, tmp_path):
    monkeypatch.setattr(gads_utils, "CACHE_DIR", tmp_path)
    parts = ["customer", "1", "search", "28d"]
    assert gads_utils.cache_get(parts) is None
    gads_utils.cache_set(parts, {"hello": "world"})
    assert gads_utils.cache_get(parts) == {"hello": "world"}


def test_cache_expires(monkeypatch, tmp_path):
    monkeypatch.setattr(gads_utils, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(gads_utils, "CACHE_TTL_SECONDS", -1)
    gads_utils.cache_set(["x"], {"a": 1})
    assert gads_utils.cache_get(["x"]) is None

"""Bid strategy recommendation rules — no API calls."""

from __future__ import annotations

import gads_bidstrategy


def test_recommend_low_volume_is_manual():
    assert gads_bidstrategy._recommend(conv=5, conv_value=0) == "MANUAL_CPC"


def test_recommend_15_to_30_is_max_conv():
    assert gads_bidstrategy._recommend(conv=20, conv_value=0) == "MAXIMIZE_CONVERSIONS"


def test_recommend_50plus_is_target_cpa():
    assert gads_bidstrategy._recommend(conv=60, conv_value=0) == "TARGET_CPA"


def test_recommend_50plus_with_value_is_target_roas():
    assert gads_bidstrategy._recommend(conv=80, conv_value=2400.0) == "TARGET_ROAS"


def test_finding_high_severity_for_starved_smart_bidding():
    item = {
        "campaign_id": "1",
        "campaign_name": "Brand Search",
        "current_strategy": "TARGET_CPA",
        "recommended": "MAXIMIZE_CONVERSIONS",
        "conversions_30d": 8.0,
    }
    f = gads_bidstrategy._finding(item)
    assert f["severity"] == "high"
    assert f["code"] == "smart_bidding_undervolume"


def test_finding_medium_when_manual_has_volume_to_graduate():
    item = {
        "campaign_id": "1",
        "campaign_name": "Brand Search",
        "current_strategy": "MANUAL_CPC",
        "recommended": "TARGET_CPA",
        "conversions_30d": 60.0,
    }
    f = gads_bidstrategy._finding(item)
    assert f["severity"] == "medium"
    assert f["code"] == "manual_with_smart_bidding_volume"


def test_finding_none_when_strategy_matches():
    item = {
        "campaign_id": "1",
        "campaign_name": "ok",
        "current_strategy": "TARGET_CPA",
        "recommended": "TARGET_CPA",
        "conversions_30d": 100.0,
    }
    assert gads_bidstrategy._finding(item) is None

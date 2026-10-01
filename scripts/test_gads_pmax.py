from unittest.mock import Mock

import gads_pmax
import pytest


@pytest.mark.parametrize("kind,resource", [
    ("channels", "campaign"), ("placements", "performance_max_placement_view"),
    ("assets", "asset_group_asset"), ("branding", "campaign_asset"),
    ("tracking", "asset_group"),
])
def test_pmax_report_scope_and_unmodified_metrics(monkeypatch, kind, resource):
    rows = [{"metrics": {"cost_micros": "1234567", "conversions": 0.25}}]
    search = Mock(return_value=rows)
    monkeypatch.setattr(gads_pmax.gads_client, "search_stream", search)
    result = gads_pmax.report("123-456-7890", 7, kind)
    cid, query = search.call_args.args
    assert cid == "1234567890"
    assert f"FROM {resource}" in query
    assert "'PERFORMANCE_MAX'" in query
    assert result["rows"] == rows
    assert result["limitations"]
    if kind == "placements":
        assert "metrics.cost_micros" not in query
        assert "metrics.conversions" not in query
    if kind in {"branding", "tracking"}:
        assert result["date_range"] is None
        assert "segments.date" not in query
    else:
        assert "BETWEEN" in query


def test_invalid_pmax_report_never_queries(monkeypatch):
    search = Mock()
    monkeypatch.setattr(gads_pmax.gads_client, "search_stream", search)
    with pytest.raises(ValueError):
        gads_pmax.report("123", 0)
    with pytest.raises(ValueError):
        gads_pmax.report("123", 7, "unsupported")
    search.assert_not_called()


def test_pmax_tracking_retains_custom_parameters(monkeypatch):
    rows = [{"asset_group": {"tracking_url_template": "{lpurl}?source={_source}",
                            "url_custom_parameters": [{"key": "source", "value": "pmax"}],
                            "final_url_suffix": "campaign=reviewed"}}]
    search = Mock(return_value=rows)
    monkeypatch.setattr(gads_pmax.gads_client, "search_stream", search)
    result = gads_pmax.report("123", kind="tracking")
    assert result["rows"] == rows and result["date_range"] is None
    assert "asset_group.url_custom_parameters" in search.call_args.args[1]

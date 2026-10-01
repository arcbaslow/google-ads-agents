from unittest.mock import Mock

import gads_demandgen
import gads_search
import pytest


@pytest.mark.parametrize("function,key,channel", [
    (gads_demandgen.channel_controls, "channel_controls", "DEMAND_GEN"),
    (gads_search.ai_max_settings, "campaigns", "SEARCH"),
])
def test_configuration_reads_preserve_scope_and_absent_values(monkeypatch, function, key, channel):
    # Unset optional fields remain absent; do not invent disabled settings.
    rows = [{"campaign": {"id": "1"}}]
    search = Mock(return_value=rows)
    monkeypatch.setattr(gads_search.gads_client, "search_stream", search)
    result = function("123-456-7890")
    cid, query = search.call_args.args
    assert cid == "1234567890"
    assert f"'{channel}'" in query
    assert "metrics." not in query
    assert "segments.date" not in query
    assert result[key] == rows
    assert result["limitations"]


def test_ai_max_migration_dates_preserved(monkeypatch):
    rows = [{"campaign": {"aca_migration_date_time": "2026-10-15 00:00:00",
                           "broad_match_migration_date_time": "2026-10-20 00:00:00"}}]
    search = Mock(return_value=rows)
    monkeypatch.setattr(gads_search.gads_client, "search_stream", search)
    assert gads_search.ai_max_settings("123")["campaigns"] == rows
    query = search.call_args.args[1]
    assert "campaign.aca_migration_date_time" in query
    assert "campaign.broad_match_migration_date_time" in query

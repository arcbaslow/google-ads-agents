import json
from unittest.mock import Mock

import gads_audit
import gads_demandgen
import pytest


def test_demand_gen_campaign_totals_preserve_account_and_date_scope(monkeypatch):
    rows = [{"campaign": {"id": "7", "status": "PAUSED"},
             "metrics": {"cost_micros": "1234567", "conversions": 0.5}}]
    search = Mock(return_value=rows)
    monkeypatch.setattr(gads_demandgen.gads_client, "search_stream", search)
    monkeypatch.setattr(gads_demandgen.gads_utils, "date_range",
                        lambda days: ("2026-09-01", "2026-09-28"))
    result = gads_demandgen.demand_gen_campaigns("123-456-7890", 28)
    customer, query = search.call_args.args
    assert customer == "1234567890"
    assert "campaign.advertising_channel_type = 'DEMAND_GEN'" in query
    assert "campaign.status != 'REMOVED'" in query
    assert "BETWEEN '2026-09-01' AND '2026-09-28'" in query
    assert "metrics.clicks" not in query
    assert "click_type" not in query  # do not filter other totals by click type
    assert result["campaigns"] == rows  # no invented currency or rounded conversions
    assert result["limitations"]


@pytest.mark.parametrize("days", [0, -1])
def test_invalid_lookback_never_reads_account(monkeypatch, days):
    search = Mock()
    monkeypatch.setattr(gads_demandgen.gads_client, "search_stream", search)
    with pytest.raises(ValueError, match="positive"):
        gads_demandgen.demand_gen_campaigns("123", days)
    search.assert_not_called()


def test_cli_empty_result_retains_limitations(monkeypatch, capsys):
    monkeypatch.setattr(gads_demandgen.gads_client, "search_stream", lambda c, q: [])
    monkeypatch.setattr("sys.argv", ["gads_demandgen", "--customer", "123", "--json"])
    assert gads_demandgen.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["campaigns"] == []
    assert result["limitations"]


def test_audit_dispatches_demand_gen_and_preserves_failures(monkeypatch):
    entry = next(entry for entry in gads_audit.DEFAULT_AGENTS if entry[0] == "gads-demandgen")
    monkeypatch.setattr(gads_audit, "DEFAULT_AGENTS", [entry])
    search = Mock(side_effect=RuntimeError("mock permission denied"))
    monkeypatch.setattr(gads_demandgen.gads_client, "search_stream", search)
    result = gads_audit.run("123", max_workers=1)
    assert result["agents"]["gads-demandgen"]["status"] == "failed"
    assert result["agents"]["gads-demandgen"]["error_code"] == "unexpected_error"

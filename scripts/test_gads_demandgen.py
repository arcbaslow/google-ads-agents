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


def test_channel_controls_cli_retains_precedence_and_real_configuration(monkeypatch, capsys):
    import gads_client
    from google.ads.googleads.client import GoogleAdsClient
    from google.auth.credentials import AnonymousCredentials

    types = GoogleAdsClient(credentials=AnonymousCredentials(), version="v25", use_proto_plus=True)
    row = types.get_type("GoogleAdsRow")
    row.campaign.id = 7
    row.ad_group.id = 8
    row.ad_group.name = "Group"
    controls = row.ad_group.demand_gen_ad_group_settings.channel_controls
    controls.selected_channels.youtube_shorts = True
    controls.selected_channels.display = False
    batch = types.get_type("SearchGoogleAdsStreamResponse")
    batch.results.append(row)
    service = Mock()
    service.search_stream.return_value = [batch]
    client = Mock()
    client.get_service.return_value = service
    monkeypatch.setattr(gads_client, "build_client", lambda: client)
    monkeypatch.setattr("sys.argv", ["demandgen", "--customer", "123", "--channel-controls",
                                     "--report", "assets", "--json"])
    assert gads_demandgen.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["channel_controls"][0]["ad_group"]["id"] == "8"
    selected = result["channel_controls"][0]["ad_group"]["demand_gen_ad_group_settings"]["channel_controls"]["selected_channels"]
    assert selected["youtube_shorts"] is True
    assert "display" not in selected  # Non-optional protobuf false is omitted by the shared mapper.
    assert service.search_stream.call_args.kwargs["query"] == gads_demandgen.CONTROLS_QUERY
    assert result["limitations"]
    service.search_stream.return_value = []
    assert gads_demandgen.main() == 0
    assert json.loads(capsys.readouterr().out)["channel_controls"] == []

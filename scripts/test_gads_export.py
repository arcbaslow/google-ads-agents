import csv
import io
import json
from unittest.mock import Mock

import gads_auth
import gads_client
import gads_export
import pytest


def test_query_is_scoped_and_limited(monkeypatch):
    read = Mock(return_value=[{"campaign": {"id": "1"}}, {"campaign": {"id": "2"}}])
    monkeypatch.setattr(gads_client, "search_stream", read)
    result = gads_export.query_rows("123-456", "SELECT campaign.id FROM campaign", 1)
    read.assert_called_once_with("123456", "SELECT campaign.id FROM campaign LIMIT 2")
    assert result["truncated"] is True and len(result["rows"]) == 1


@pytest.mark.parametrize("query", ["DELETE FROM campaign", "SELECT * FROM campaign",
    "SELECT campaign.id FROM campaign; SELECT campaign.name FROM campaign",
    "SELECT campaign.id FROM campaign LIMIT 1", "SELECT campaign.id FROM campaign PARAMETERS include_drafts=true",
    "SELECT campaign.id FROM campaign -- comment", "SELECT campaign.id FROM campaign WHERE campaign.name = 'unclosed"])
def test_invalid_query_rejected_before_auth(monkeypatch, query):
    read = Mock()
    monkeypatch.setattr(gads_client, "search_stream", read)
    with pytest.raises(ValueError):
        gads_export.query_rows("123", query)
    read.assert_not_called()


def test_query_preserves_quoted_text_and_checks_session(monkeypatch):
    read = Mock(return_value=[])
    monkeypatch.setattr(gads_client, "search_stream", read)
    query = "SELECT campaign.name FROM campaign WHERE campaign.name = 'LIMIT and FROM' ORDER BY campaign.id"
    assert not gads_export.query_rows("123", query)["truncated"]
    assert read.call_args.args[1].startswith(query)
    monkeypatch.undo()
    provider = Mock()
    provider.get_credentials.side_effect = gads_auth.SessionExpiredError("expired")
    import gads_provider
    with gads_provider.bind_provider(provider), pytest.raises(gads_auth.SessionExpiredError):
        gads_export.query_rows("123", "SELECT campaign.id FROM campaign")


def test_multi_account_nested_findings_and_failures():
    doc = {"accounts": {
        "123": {"agents": {"demo": {"status": "ok", "age": {"findings": [
            {"severity": "high", "code": "age", "message": "review", "entity": {"campaign_id": "7"}},
        ]}}, "search": {"status": "failed", "error_code": "permission_denied", "error": "private"}}},
        "456": {"agents": {}},
    }, "discovery": {"status": "partial", "errors": [{"error": "private"}]}}
    rows = gads_export.audit_rows(doc)
    finding = next(r for r in rows if r["kind"] == "finding")
    assert finding["customer_id"] == "123" and finding["source_path"] == "age"
    assert "private" not in json.dumps(rows)
    metrics = gads_export.prometheus_text(rows)
    assert 'gads_findings{customer_id="123",severity="high"} 1' in metrics
    assert 'gads_failed_adapters{customer_id="123"} 1' in metrics
    assert 'gads_findings{customer_id="456",severity="high"} 0' in metrics
    assert 'gads_discovery_incomplete 1' in metrics


def test_csv_flattens_and_defuses_formulas_without_changing_numbers():
    rows = [{"campaign": {"name": "=HYPERLINK(\"https://example.test\")"}, "cost": -1.5,
             "note": "\t@SUM(1)", "values": ["a", "b"]}]
    text = gads_export.csv_text(rows)
    row = next(csv.DictReader(io.StringIO(text)))
    assert row["campaign.name"].startswith("'=") and row["note"].startswith("'\t@")
    assert row["cost"] == "-1.5" and json.loads(row["values"]) == ["a", "b"]
    assert rows[0]["campaign"]["name"].startswith("=")


def test_saved_export_never_builds_client(tmp_path, monkeypatch, capsys):
    source = tmp_path / "audit.json"
    source.write_text(json.dumps({"customer_id": "123", "agents": {}}))
    build = Mock(side_effect=AssertionError("No credentials for saved exports"))
    monkeypatch.setattr(gads_client, "build_client", build)
    monkeypatch.setattr("sys.argv", ["export", "--audit-file", str(source), "--format", "prometheus"])
    assert gads_export.main() == 0
    assert 'gads_failed_adapters{customer_id="123"} 0' in capsys.readouterr().out
    build.assert_not_called()


def test_query_failure_does_not_overwrite_existing_export(tmp_path, monkeypatch, capsys):
    source, target = tmp_path / "query.gaql", tmp_path / "report.csv"
    source.write_text("SELECT campaign.id FROM campaign")
    target.write_text("previous export")
    monkeypatch.setattr(gads_client, "search_stream", Mock(side_effect=ValueError("private")))
    monkeypatch.setattr("sys.argv", ["export", "--query-file", str(source), "--customer", "123", "--output", str(target)])
    assert gads_export.main() == 3
    assert target.read_text() == "previous export"
    assert "private" not in capsys.readouterr().out


def test_malformed_audit_rejected():
    with pytest.raises(ValueError):
        gads_export.audit_rows({"accounts": {"123": {"agents": []}}})

"""Execute fixture contracts offline; this does not evaluate a language model."""

import json
from pathlib import Path
from unittest.mock import Mock

import gads_auth
import gads_client
import gads_creation
import gads_export
import gads_provider
import pytest
from google.ads.googleads.client import GoogleAdsClient
from google.auth.credentials import AnonymousCredentials

CASES = json.loads((Path(__file__).parent.parent / "examples/evals/safety_cases.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_offline_safety_contract(case, tmp_path, monkeypatch, capsys):
    assert case["prompt"] and case["rubric"]
    service = Mock()
    types = GoogleAdsClient(credentials=AnonymousCredentials(), version="v25", use_proto_plus=True)
    service.mutate.return_value = types.get_type("MutateGoogleAdsResponse")
    client = Mock(get_type=types.get_type)
    client.get_service.return_value = service
    if case["runner"] == "search":
        build = Mock(return_value=client)
        monkeypatch.setattr(gads_client, "build_client", build)
        source = tmp_path / "search-spec.json"
        source.write_text(json.dumps(case["spec"]))
        monkeypatch.setattr("sys.argv", ["create", "--customer", "123", "--search-spec", str(source), case["mode"], "--json"])

        def approve():
            assert not service.mutate.called
            preview = capsys.readouterr().err
            assert '"PAUSED"' in preview and '"budget_micros"' not in preview
            assert '"amount_micros": "50000000"' in preview
            return case["answer"]

        monkeypatch.setattr("builtins.input", approve)
        exit_code = gads_creation.main()
        assert [c.kwargs["validate_only"] for c in service.mutate.call_args_list] == case["expected_calls"]
        if case.get("expected_error") == "invalid_request":
            build.assert_not_called()
    elif case["runner"] == "query":
        source = tmp_path / "query.gaql"
        source.write_text(case["query"])
        monkeypatch.setattr("sys.argv", ["export", "--customer", "123", "--query-file", str(source)])
        provider = Mock()
        provider.get_credentials.side_effect = gads_auth.SessionExpiredError("expired")
        with gads_provider.bind_provider(provider):
            exit_code = gads_export.main()
        provider.get_credentials.assert_called_once()
    else:
        source = tmp_path / "audit.json"
        source.write_text(json.dumps(case["audit"]))
        monkeypatch.setattr(gads_client, "build_client", Mock(side_effect=AssertionError("Offline export")))
        monkeypatch.setattr("sys.argv", ["export", "--audit-file", str(source)])
        exit_code = gads_export.main()
    assert exit_code == case["expected_exit"]
    result = json.loads(capsys.readouterr().out)
    if "expected_error" in case:
        assert result["error_code"] == case["expected_error"]
    elif "expected_status" in case:
        assert result["status"] == case["expected_status"]
    else:
        assert any(r.get("error_code") == "permission_denied" for r in result["rows"])
        finding = next(r for r in result["rows"] if r["kind"] == "finding")
        assert finding["entity"]["campaign_id"] == "7" and finding["source_path"] == "age"

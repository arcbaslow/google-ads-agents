from unittest.mock import Mock

import gads_conversions
import gads_gtag
import pytest


def test_empty_upload_diagnostics_do_not_claim_success(monkeypatch):
    search = Mock(return_value=[])
    monkeypatch.setattr(gads_conversions.gads_client, "search_stream", search)
    result = gads_conversions.upload_diagnostics("123-456-7890")
    assert result["upload_diagnostics"] == []
    assert result["limitations"]
    assert search.call_args.args[0] == "1234567890"
    assert "FROM offline_conversion_upload_client_summary" in search.call_args.args[1]


def test_conversion_read_failure_does_not_become_empty_success(monkeypatch):
    monkeypatch.setattr(gads_conversions.gads_client, "search_stream",
                        Mock(side_effect=PermissionError("test denial")))
    with pytest.raises(PermissionError):
        gads_conversions.upload_diagnostics("123")


@pytest.mark.parametrize("html,signals", [
    (b"<html>no tag</html>", []),
    (b"<!-- ad_user_data ad_personalization -->", ["ad_user_data", "ad_personalization"]),
])
def test_static_consent_evidence_never_claims_runtime_verification(monkeypatch, html, signals):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = html
    monkeypatch.setattr(gads_gtag.urllib.request, "urlopen", Mock(return_value=response))
    result = gads_gtag.scan_site("https://example.test")
    assert result["consent_evidence"]["mentioned_in_html"] == signals
    assert result["consent_evidence"]["runtime_verified"] is False
    assert result["consent_evidence"]["limitations"]

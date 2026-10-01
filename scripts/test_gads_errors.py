import json

import gads_audit
import gads_errors
import pytest
from google.api_core import exceptions
from google.auth.exceptions import RefreshError


@pytest.mark.parametrize("exc,code,retryable", [
    (RuntimeError("PRIVATE"), "unexpected_error", False),
    (exceptions.PermissionDenied("PRIVATE"), "permission_denied", False),
    (exceptions.ServiceUnavailable("PRIVATE"), "temporarily_unavailable", True),
    (RefreshError("PRIVATE"), "authentication_required", False),
    (RefreshError("PRIVATE", retryable=True), "temporarily_unavailable", True),
    (ValueError("PRIVATE"), "invalid_request", False),
])
def test_audit_errors_are_structured_and_redacted(exc, code, retryable):
    def fail():
        raise exc

    result = gads_audit._safe(fail)
    assert result["status"] == "failed"
    assert result["error_code"] == code
    assert result["retryable"] is retryable
    assert "PRIVATE" not in json.dumps(result)
    assert "traceback" not in result


def test_partial_audit_keeps_successful_results(monkeypatch):
    def fail(*args):
        raise exceptions.PermissionDenied("PRIVATE")

    monkeypatch.setattr(gads_audit, "DEFAULT_AGENTS", [
        ("failed", fail), ("empty", lambda *args: {"rows": []}),
    ])
    result = gads_audit.run("123")
    assert result["agents"]["failed"]["error_code"] == "permission_denied"
    assert result["agents"]["empty"] == {"rows": [], "status": "ok"}


def test_google_ads_error_details_are_not_returned():
    from google.ads.googleads.errors import GoogleAdsException
    from google.ads.googleads.v25.errors.types.errors import GoogleAdsFailure

    failure = GoogleAdsFailure(errors=[{
        "error_code": {"authorization_error": "USER_PERMISSION_DENIED"}, "message": "PRIVATE",
    }])
    result = gads_errors.describe(GoogleAdsException(None, None, failure, "PRIVATE"))
    assert result["error_code"] == "permission_denied"
    assert "PRIVATE" not in json.dumps(result)


@pytest.mark.parametrize("method", ["gcloud_adc", "oauth_client"])
def test_local_auth_check_does_not_echo_backend_text(monkeypatch, capsys, method):
    from unittest.mock import Mock

    import gads_auth
    import gads_authflow

    monkeypatch.setattr(gads_auth, "enforce_session", lambda: None)
    monkeypatch.setattr(gads_auth, "active_profile_name", lambda: "example")
    monkeypatch.setattr(gads_auth, "active_profile", lambda: {"auth_method": method})
    backend = Mock()
    backend.credentials.side_effect = RefreshError("PRIVATE provider body")
    monkeypatch.setattr(gads_authflow, "select_backend", lambda *args: backend)
    assert gads_auth.cmd_check(None) == 1
    result = capsys.readouterr().out
    assert "PRIVATE" not in result
    assert "gcloud" in result if method == "gcloud_adc" else "--oauth-login" in result


def test_history_cli_does_not_echo_provider_text(monkeypatch, capsys):
    from unittest.mock import Mock

    import gads_client
    import gads_history

    monkeypatch.setattr(gads_client, "search_stream", Mock(side_effect=exceptions.Forbidden("PRIVATE")))
    monkeypatch.setattr("sys.argv", ["history", "--customer", "123", "--changes", "--json"])
    assert gads_history.main() == 3
    output = capsys.readouterr().out
    assert "PRIVATE" not in output
    assert json.loads(output)["error_code"] == "permission_denied"

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

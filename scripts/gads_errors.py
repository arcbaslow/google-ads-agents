"""Public error categories without provider messages or request contents."""

import json
import urllib.error
from functools import wraps

from google.api_core import exceptions as api_errors
from google.auth.exceptions import RefreshError


def describe(exc: Exception) -> dict:
    from gads_auth import AuthRequiredError, SessionExpiredError
    from gads_mutate import MutationCancelled

    code, message, retryable = "unexpected_error", "Operation failed; inspect configuration and inputs.", False
    if isinstance(exc, MutationCancelled):
        code, message = "cancelled", "Operation cancelled; no changes sent."
    elif isinstance(exc, RefreshError):
        if exc.retryable:
            code, message, retryable = "temporarily_unavailable", "Authentication service temporarily unavailable.", True
        else:
            code, message = "authentication_required", "Reconnect the Google account."
    elif isinstance(exc, (AuthRequiredError, SessionExpiredError, api_errors.Unauthorized)):
        code, message = "authentication_required", "Sign in again; check the session and credentials."
    elif isinstance(exc, api_errors.Forbidden) or isinstance(exc, urllib.error.HTTPError) and exc.code == 403:
        code, message = "permission_denied", "Check account permissions and Cloud project access."
    elif isinstance(exc, urllib.error.HTTPError):
        code, message = "http_error", "HTTP request failed."
        retryable = exc.code == 429 or exc.code >= 500
    elif isinstance(exc, (api_errors.ServiceUnavailable, api_errors.DeadlineExceeded,
                          api_errors.TooManyRequests, TimeoutError, ConnectionError)):
        code, message, retryable = "temporarily_unavailable", "Service temporarily unavailable; retry the read later.", True
    elif isinstance(exc, api_errors.NotFound):
        code, message = "not_found", "The requested resource is unavailable."
    elif isinstance(exc, (ValueError, api_errors.InvalidArgument)):
        code, message = "invalid_request", "Check the supplied input and supported fields."
    else:
        from google.ads.googleads.errors import GoogleAdsException
        if isinstance(exc, GoogleAdsException):
            # Error messages and field paths may contain submitted private data.
            kinds = {e.error_code._pb.WhichOneof("error_code") for e in exc.failure.errors}
            if "authentication_error" in kinds:
                code, message = "authentication_required", "Reconnect the Google account."
            elif "authorization_error" in kinds:
                code, message = "permission_denied", "Check account permissions and Cloud project access."
            elif kinds & {"quota_error", "internal_error"}:
                code, message, retryable = "temporarily_unavailable", "Service temporarily unavailable; retry the read later.", True
            else:
                code, message = "api_rejected", "Google Ads rejected the request; check supported fields and inputs."
    return {"status": "failed", "error_code": code, "error": message, "retryable": retryable}


def cli(entrypoint):
    """Keep unexpected provider text and tracebacks out of read-command output."""
    @wraps(entrypoint)
    def run():
        try:
            return entrypoint()
        except Exception as exc:
            print(json.dumps(describe(exc)))
            return 3
    return run

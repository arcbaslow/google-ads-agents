"""Credential-resolution seam.

build_client() resolves credentials through the *active* CredentialProvider.
The CLI default (FileCredentialProvider) wraps gads_auth unchanged. The web app
binds a per-request provider via bind_provider(); the contextvar isolates it
across concurrent requests. This module owns the contextvar and registry so the
toolkit never has to import the web app.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Any, Protocol


class CredentialProvider(Protocol):
    def get_credentials(self) -> Any: ...
    def get_developer_token(self) -> str: ...
    def get_login_customer_id(self) -> str | None: ...


class FileCredentialProvider:
    """Default: resolve from the active local profile via gads_auth."""

    def get_credentials(self) -> Any:
        import gads_auth
        return gads_auth.get_credentials()

    def get_developer_token(self) -> str:
        import gads_auth
        return gads_auth.get_developer_token()

    def get_login_customer_id(self) -> str | None:
        import gads_auth
        return gads_auth.get_login_customer_id()


_default = FileCredentialProvider()
_active: contextvars.ContextVar = contextvars.ContextVar("gads_active_provider", default=None)


def get_active_provider() -> CredentialProvider:
    return _active.get() or _default


@contextmanager
def bind_provider(provider: CredentialProvider):
    token = _active.set(provider)
    try:
        yield
    finally:
        _active.reset(token)

"""Token storage seam.

LocalFileTokenStore keeps OAuth material inside the existing credentials file
(behind this interface). The future web app implements a DbTokenStore keyed by
user id with the same get/set contract, so auth backends and gads_client need
no change.
"""

from __future__ import annotations

from typing import Any, Protocol

import gads_auth

_OAUTH_FIELDS = ("client_id", "client_secret", "refresh_token")


class TokenStore(Protocol):
    def get(self, key: str) -> dict[str, Any] | None: ...
    def set(self, key: str, record: dict[str, Any]) -> None: ...


class LocalFileTokenStore:
    """OAuth material lives inside the profile named `key`, file mode 0600."""

    def get(self, key: str) -> dict[str, Any] | None:
        prof = gads_auth._profiles().get("profiles", {}).get(key)
        if not prof or not prof.get("refresh_token"):
            return None
        return {f: prof.get(f) for f in _OAUTH_FIELDS}

    def set(self, key: str, record: dict[str, Any]) -> None:
        data = gads_auth._profiles()
        prof = data.setdefault("profiles", {}).setdefault(key, {})
        for f in _OAUTH_FIELDS:
            if f in record:
                prof[f] = record[f]
        gads_auth.save_credentials(data)

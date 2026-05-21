"""Pytest config — point credential paths at a temp dir per test."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_paths(tmp_path: Path, monkeypatch) -> None:
    """Every test gets a clean credentials/session dir."""
    import gads_auth

    creds = tmp_path / "gads-credentials.json"
    session = tmp_path / "gads-session.json"
    monkeypatch.setattr(gads_auth, "CREDENTIALS_PATH", creds)
    monkeypatch.setattr(gads_auth, "SESSION_PATH", session)
    # Avoid leaking host env into tests
    for k in ("GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_LOGIN_CUSTOMER_ID"):
        monkeypatch.delenv(k, raising=False)

"""Credential writes must be atomic.

`_save` is the single write path for the profile store: developer tokens for
every MCC, and under the own-OAuth-client backend the refresh tokens too. It
used to open the real path with "w", which truncates before anything is
written, so an interruption between truncate and flush emptied the file and
lost every credential with no backup.
"""

import json

import gads_auth
import pytest


def test_save_writes_and_reloads(tmp_path):
    path = tmp_path / "creds.json"
    gads_auth._save(path, {"profiles": {"acme": {"developer_token": "T"}}})
    assert json.loads(path.read_text())["profiles"]["acme"]["developer_token"] == "T"


def test_failed_save_leaves_the_previous_file_intact(tmp_path, monkeypatch):
    """The whole point: a crash mid-write must not destroy what was there."""
    path = tmp_path / "creds.json"
    gads_auth._save(path, {"profiles": {"acme": {"developer_token": "ORIGINAL"}}})

    def boom(*a, **k):
        raise KeyboardInterrupt("interrupted mid-write")

    monkeypatch.setattr(gads_auth.json, "dump", boom)
    with pytest.raises(KeyboardInterrupt):
        gads_auth._save(path, {"profiles": {"acme": {"developer_token": "REPLACEMENT"}}})

    # Old content survives, byte for byte.
    assert json.loads(path.read_text())["profiles"]["acme"]["developer_token"] == "ORIGINAL"


def test_failed_save_leaves_no_temp_files_behind(tmp_path, monkeypatch):
    path = tmp_path / "creds.json"
    gads_auth._save(path, {"profiles": {}})

    monkeypatch.setattr(
        gads_auth.json, "dump", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
    )
    with pytest.raises(OSError):
        gads_auth._save(path, {"profiles": {"x": {}}})

    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "creds.json"]
    assert leftovers == [], f"temp files left behind: {leftovers}"


def test_save_replaces_rather_than_truncates(tmp_path):
    """A reader must never observe a half-written file.

    Approximated by checking the target is never zero-length at any point a
    reader could see it: after a successful save it holds complete JSON, and
    the failure cases above prove the original survives.
    """
    path = tmp_path / "creds.json"
    big = {"profiles": {f"mcc{i}": {"developer_token": "T" * 200} for i in range(50)}}
    gads_auth._save(path, big)
    assert json.loads(path.read_text()) == big
    assert path.stat().st_size > 1000
